#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import argparse
import os
import platform
import shlex
import shutil
import sys

from pathlib import Path
from typing import List, Set

SCRIPT_DIR = Path(__file__).parent
REPO_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR / "utils"))

from utils import get_logger, is_linux, is_macOS, is_windows, run  # noqa: E402

log = get_logger("build")


class UsageError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _check_python_version():
    # Require python 3.6+
    if sys.version_info[0] != 3:
        raise UsageError("Bad python major version: expecting python 3, found version " "'{}'".format(sys.version))
    if sys.version_info[1] < 6:
        raise UsageError("Bad python minor version: expecting python 3.6+, found version " "'{}'".format(sys.version))


_check_python_version()


def _parse_arguments():
    class Parser(argparse.ArgumentParser):
        # override argument file line parsing behavior - allow multiple arguments per line and handle quotes
        def convert_arg_line_to_args(self, arg_line):
            return shlex.split(arg_line)

    parser = Parser(
        description="ONNXRuntime Extensions Shared Library build driver.",
        usage="""
        There are 3 phases which can be individually selected.

        The Update (--update) phase will update git submodules and run cmake to generate makefiles.
        The Build (--build) phase will build all projects.
        The Test (--test) phase will run all unit tests.

        Default behavior is --update --build --test for native architecture builds.
        Default behavior is --update --build for cross-compiled builds.

        If phases are explicitly specified only those phases will be run. 
          e.g. run with `--build` to rebuild without running the update or test phases
        """,

        # files containing arguments can be specified on the command line with "@<filename>" and the arguments within
        # will be included at that point
        fromfile_prefix_chars="@",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Main arguments
    parser.add_argument("--build_dir", type=Path,
                        # We set the default programmatically as it needs to take into account whether we're
                        # cross-compiling
                        help="Path to the build directory. Defaults to 'build/<target platform>'")
    parser.add_argument("--config", nargs="+", default=["Debug"],
                        choices=["Debug", "MinSizeRel", "Release", "RelWithDebInfo"],
                        help="Configuration(s) to build.")
    parser.add_argument("--update", action="store_true", help="Update submodules and makefiles.")
    parser.add_argument("--build", action="store_true", help="Build.")
    parser.add_argument("--test", action="store_true", help="Run unit tests.")

    parser.add_argument("--clean", action="store_true",
                        help="Run 'cmake --build --target clean' for the selected config/s.")

    parser.add_argument("--skip_submodule_sync", action="store_true",
                        help="Don't run 'git submodule update'. Makes the Update phase faster on Windows machines.")
    parser.add_argument("--skip_tests", action="store_true", help="Skip all tests.")

    parser.add_argument("--parallel", nargs="?", const="0", default="1", type=int,
                        help="Use parallel build. The optional value specifies the maximum number of parallel jobs. "
                             "If the optional value is 0 or unspecified, it is interpreted as the number of CPUs.")

    parser.add_argument("--cmake_extra_defines", nargs="+", action="append",
                        help="Extra definitions to pass to CMake during build system generation. "
                             "These are essentially CMake -D options without the leading -D. "
                             "Multiple name=value defines can be specified, with each separated by a space. "
                             "Quote the name and value if the value contains spaces. "
                             "The cmake_extra_defines can also be specified multiple times. "
                             "  e.g. --cmake_extra_defines \"Name1=the value\" Name2=value2")

    # Test options
    parser.add_argument("--enable_unit_tests", action="store_true",
                        help="Enable the C++ unit tests. onnxruntime_lib_dir must also be provided.")

    parser.add_argument("--onnxruntime_lib_dir", type=Path,
                        help="Path to directory containing the pre-built ONNX Runtime library. "
                             "Required if enable_unit_tests is True.")
    # ARM options
    parser.add_argument("--arm", action="store_true",
                        help="[cross-compiling] Create ARM makefiles. Requires --update and no existing cache "
                             "CMake setup. Delete CMakeCache.txt if needed")
    parser.add_argument("--arm64", action="store_true",
                        help="[cross-compiling] Create ARM64 makefiles. Requires --update and no existing cache "
                             "CMake setup. Delete CMakeCache.txt if needed")
    parser.add_argument("--arm64ec", action="store_true",
                        help="[cross-compiling] Create ARM64EC makefiles. Requires --update and no existing cache "
                             "CMake setup. Delete CMakeCache.txt if needed")

    # parser.add_argument("--msvc_toolset", help="MSVC toolset to use. e.g. 14.11")

    # Android options
    parser.add_argument("--android", action="store_true", help="Build for Android")
    parser.add_argument("--android_abi", default="arm64-v8a", choices=["armeabi-v7a", "arm64-v8a", "x86", "x86_64"],
                        help="Specify the target Android Application Binary Interface (ABI)")
    parser.add_argument("--android_api", type=int, default=27, help="Android API Level, e.g. 21")
    parser.add_argument("--android_home", type=Path, default=os.environ.get("ANDROID_HOME"),
                        help="Path to the Android SDK.")
    parser.add_argument("--android_ndk_path", type=Path, default=os.environ.get("ANDROID_NDK_HOME"),
                        help="Path to the Android NDK. Typically `<Android SDK>/ndk/<ndk_version>")

    # iOS options
    parser.add_argument("--build_apple_framework", action="store_true",
                        help="Build a macOS/iOS framework for the ONNXRuntime.")

    parser.add_argument("--ios", action="store_true", help="build for ios")
    parser.add_argument("--ios_sysroot", default="",
                        help="Specify the name of the platform SDK to be used. e.g. iphoneos, iphonesimulator")
    parser.add_argument("--ios_toolchain_file", default=f"{REPO_DIR}/cmake/ortext_ios.toolchain.cmake", type=Path,
                        help="Path to ios toolchain file. Default is <repo>/cmake/ortext_ios.toolchain.cmake")
    parser.add_argument("--xcode_code_signing_team_id", default="",
                        help="The development team ID used for code signing in Xcode")
    parser.add_argument("--xcode_code_signing_identity", default="",
                        help="The development identity used for code signing in Xcode")
    parser.add_argument("--use_xcode", action="store_true",
                        help="Use Xcode as cmake generator, this is only supported on MacOS.")
    parser.add_argument("--osx_arch", default="arm64" if platform.machine() == "arm64" else "x86_64",
                        choices=["arm64", "arm64e", "x86_64"],
                        help="Specify the Target specific architectures for macOS and iOS. "
                             "This is only supported on MacOS")
    parser.add_argument("--apple_deploy_target", type=str,
                        help="Specify the minimum version of the target platform (e.g. macOS or iOS). "
                             "This is only supported on MacOS")

    # WebAssembly options
    parser.add_argument("--build_wasm", action="store_true", help="Build for WebAssembly")
    parser.add_argument("--build_wasm_static_lib", action="store_true", help="Build for WebAssembly static library")

    parser.add_argument("--enable_wasm_simd", action="store_true", help="Enable WebAssembly SIMD")
    parser.add_argument("--enable_wasm_threads", action="store_true", help="Enable WebAssembly multi-threads support")

    parser.add_argument("--disable_wasm_exception_catching", action="store_true",
                        help="Disable exception catching in WebAssembly.")
    parser.add_argument("--enable_wasm_exception_throwing_override", action="store_true",
                        help="Enable exception throwing in WebAssembly, this will override default disabling exception "
                             "throwing behavior when disable exceptions.")

    parser.add_argument("--enable_wasm_debug_info", action="store_true",
                        help="Build WebAssembly with DWARF format debug info")

    parser.add_argument("--emsdk_version", default="3.1.19", help="Specify version of emsdk")
    parser.add_argument("--emscripten_settings", nargs="+", action="append",
                        help="Extra emscripten settings to pass to emcc using '-s <key>=<value>' during build.")

    # x86 args
    # TODO: Are these needed?
    parser.add_argument("--x86", action="store_true",
                        help="[cross-compiling] Create Windows x86 makefiles. Requires --update and no existing cache "
                             "CMake setup. Delete CMakeCache.txt if needed")

    # Arguments needed by CI
    parser.add_argument("--cmake_path", default="cmake", type=Path, help="Path to the CMake program.")

    parser.add_argument("--ctest_path", default="ctest",
                        help="Optional path to the CTest program. If not provided the test programs will be run "
                             "directly.",
    )
    parser.add_argument("--cmake_generator",
                        choices=["Visual Studio 16 2019", "Visual Studio 17 2022", "Ninja"],
                        default="Visual Studio 17 2022" if is_windows() else None,
                        help="Specify the generator that CMake invokes. This is only supported on Windows")

    # Binary size reduction options
    parser.add_argument("--include_ops_by_config", type=Path,
                        help="Only include ops specified in the build that are listed in this config file. "
                             "Format of config file is `domain;opset;op1,op2,... "
                             "  e.g. com.microsoft.extensions;1;ImageDecode,ImageEncode")

    args = parser.parse_args()

    if not args.build_dir:
        build_dir = f"build/{platform.system()}"

        # override if we're cross-compiling
        if args.android:
            build_dir = "build/Android"
        elif args.ios:
            build_dir = "build/iOS"
        elif args.arm:
            build_dir = "build/arm"
        elif args.arm64:
            build_dir = "build/arm64"
        elif args.arm64ec:
            build_dir = "build/arm64ec"

        args.build_dir = Path(build_dir)

    return args


def _is_reduced_ops_build(args):
    return args.include_ops_by_config is not None


def _resolve_executable_path(command_or_path: Path):
    """Returns the absolute path of an executable."""

    exe_path = None
    if command_or_path:
        executable_path = shutil.which(str(command_or_path))
        if executable_path is None:
            raise UsageError(f"Failed to resolve executable path for '{command_or_path}'.")

        exe_path = Path(executable_path)

    return exe_path


def _get_build_config_dir(build_dir: Path, config: str):
    # build directory per configuration
    return build_dir / config


def _run_subprocess(args: List[str], cwd: Path = None, capture_stdout=False, shell=False, env=None,
                    python_path: Path = None):

    if isinstance(args, str):
        raise ValueError("args should be a sequence of strings, not a string")

    if env is None:
        env = {}

    my_env = os.environ.copy()

    if python_path:
        python_path = str(python_path.resolve())
        if "PYTHONPATH" in my_env:
            my_env["PYTHONPATH"] += os.pathsep + python_path
        else:
            my_env["PYTHONPATH"] = python_path

    my_env.update(env)

    return run(*args, cwd=cwd, capture_stdout=capture_stdout, shell=shell, env=my_env)


def _update_submodules(source_dir: Path):
    _run_subprocess(["git", "submodule", "sync", "--recursive"], cwd=source_dir)
    _run_subprocess(["git", "submodule", "update", "--init", "--recursive"], cwd=source_dir)


def _flatten_arg_list(nested_list: List[List[str]]):
    return [i for j in nested_list for i in j] if nested_list else []


def _is_cross_compiling_on_apple(args):
    if is_macOS():
        return args.ios or args.osx_arch != platform.machine()

    return False


def _validate_unit_test_args(args):
    if not args.onnxruntime_lib_dir:
        raise UsageError("onnxruntime_lib_dir must be specified if enable_unit_tests is True")

    ort_lib_dir = args.onnxruntime_lib_dir.resolve(strict=True)
    if not ort_lib_dir.is_dir():
        raise UsageError("onnxruntime_lib_dir must be a directory")

    return ort_lib_dir


def _generate_selected_ops_config(config_file: Path):
    config_file.resolve(strict=True)
    script = REPO_DIR / "tools" / "gen_selectedops.py"
    _run_subprocess([sys.executable, str(script), str(config_file)])


def _generate_build_tree(cmake_path: Path,
                         source_dir: Path,
                         build_dir: Path,
                         configs: Set[str],
                         cmake_extra_defines: List[str],
                         args,
                         cmake_extra_args: List[str]
                         ):
    log.info("Generating CMake build tree")

    cmake_args = [
        str(cmake_path),
        str(source_dir),
        # There are two ways of locating python C API header file. "find_package(PythonLibs 3.5 REQUIRED)"
        # and "find_package(Python 3.5 COMPONENTS Development.Module)". The first one is deprecated and it
        # depends on the "PYTHON_EXECUTABLE" variable. The second needs "Python_EXECUTABLE". Here we set both
        # of them to get the best compatibility.
        "-DPython_EXECUTABLE=" + sys.executable,
        "-DPYTHON_EXECUTABLE=" + sys.executable,
        "-DOCOS_BUILD_APPLE_FRAMEWORK=" + ("ON" if args.build_apple_framework else "OFF"),
        # By default - we currently support only cross compiling for ARM/ARM64
        # (no native compilation supported through this script).
        "-DOCOS_CROSS_COMPILING=" + ("ON" if args.arm64 or args.arm64ec or args.arm else "OFF"),
        "-DOCOS_ENABLE_SELECTED_OPLIST=" + ("ON" if _is_reduced_ops_build(args) else "OFF"),
    ]

    if args.enable_unit_tests:
        ort_lib_dir = _validate_unit_test_args(args)
        cmake_args += [
            "-DOCOS_ENABLE_CTEST=ON",
            "-DONNXRUNTIME_LIB_DIR=" + str(ort_lib_dir)
        ]

    if args.build_wasm:
        cmake_args += [
            "-DOCOS_BUILD_WEBASSEMBLY=" + ("ON" if args.build_wasm else "OFF"),
            "-DOCOS_BUILD_WEBASSEMBLY_STATIC_LIB=" + ("ON" if args.build_wasm_static_lib else "OFF"),
            "-DOCOS_ENABLE_WEBASSEMBLY_EXCEPTION_CATCHING="
            + ("OFF" if args.disable_wasm_exception_catching else "ON"),
            "-DOCOS_ENABLE_WEBASSEMBLY_EXCEPTION_THROWING="
            + ("ON" if args.enable_wasm_exception_throwing_override else "OFF"),
            "-DOCOS_ENABLE_WEBASSEMBLY_THREADS=" + ("ON" if args.enable_wasm_threads else "OFF"),
            "-DOCOS_ENABLE_WEBASSEMBLY_DEBUG_INFO=" + ("ON" if args.enable_wasm_debug_info else "OFF"),
            "-DOCOS_ENABLE_WEBASSEMBLY_SIMD=" + ("ON" if args.enable_wasm_simd else "OFF")
        ]

    if args.android:
        if not args.android_ndk_path:
            raise UsageError("android_ndk_path is required to build for Android")
        if not args.android_home:
            raise UsageError("android_home is required to build for Android")

        android_home = args.android_home.resolve(strict=True)
        android_ndk_path = args.android_ndk_path.resolve(strict=True)

        if not android_home.is_dir() or not android_ndk_path.is_dir():
            raise UsageError("Android home and NDK paths must be directories.")

        ndk_version = android_ndk_path.name  # NDK version is inferred from the folder name

        cmake_args += [
            "-DOCOS_BUILD_ANDROID=ON",
            "-DCMAKE_TOOLCHAIN_FILE="
            + str((args.android_ndk_path / "build" / "cmake" / "android.toolchain.cmake").resolve(strict=True)),
            "-DANDROID_NDK_VERSION=" + str(ndk_version),
            "-DANDROID_PLATFORM=android-" + str(args.android_api),
            "-DANDROID_ABI=" + str(args.android_abi)
        ]

    if args.ios:
        required_args = [
            args.use_xcode,
            args.ios_sysroot,
            args.apple_deploy_target,
        ]

        arg_names = [
            "--use_xcode            " + "<need use xcode to cross build iOS on MacOS>",
            "--ios_sysroot          " + "<the location or name of the macOS platform SDK>",
            "--apple_deploy_target  " + "<the minimum version of the target platform>",
        ]

        if not all(required_args):
            raise UsageError("iOS build on MacOS canceled due to missing required arguments: "
                             + ", ".join(val for val, cond in zip(arg_names, required_args) if not cond))

        cmake_args += [
            "-DCMAKE_SYSTEM_NAME=iOS",
            "-DCMAKE_OSX_SYSROOT=" + args.ios_sysroot,
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=" + args.apple_deploy_target,
            "-DCMAKE_TOOLCHAIN_FILE=" + str(args.ios_toolchain_file.resolve(strict=True)),
        ]

    if args.build_wasm:
        emsdk_dir = source_dir / "cmake" / "external" / "emsdk"
        emscripten_cmake_toolchain_file = \
            emsdk_dir / "upstream" / "emscripten" / "cmake" / "Modules" / "Platform" / "Emscripten.cmake"

        cmake_args += ["-DCMAKE_TOOLCHAIN_FILE=" + str(emscripten_cmake_toolchain_file)]

        # add default emscripten settings
        emscripten_settings = _flatten_arg_list(args.emscripten_settings)

        if emscripten_settings:
            cmake_args += [f"-DOCOS_EMSCRIPTEN_SETTINGS={';'.join(emscripten_settings)}"]

    cmake_args += ["-D{}".format(define) for define in cmake_extra_defines]

    cmake_args += cmake_extra_args

    for config in configs:
        config_build_dir = _get_build_config_dir(build_dir, config)
        os.makedirs(config_build_dir, exist_ok=True)

        _run_subprocess(cmake_args + [f"-DCMAKE_BUILD_TYPE={config}"], cwd=config_build_dir)


def clean_targets(cmake_path, build_dir: Path, configs: Set[str]):
    for config in configs:
        log.info("Cleaning targets for %s configuration", config)
        build_dir2 = _get_build_config_dir(build_dir, config)
        cmd_args = [cmake_path, "--build", build_dir2, "--config", config, "--target", "clean"]

        _run_subprocess(cmd_args)


def build_targets(args, cmake_path: Path, build_dir: Path, configs: Set[str], num_parallel_jobs: int):

    env = {}
    if args.android:
        env["ANDROID_HOME"] = str(args.android_home)
        env["ANDROID_NDK_HOME"] = str(args.android_ndk_path)

    for config in configs:
        log.info("Building targets for %s configuration", config)
        build_dir2 = _get_build_config_dir(build_dir, config)
        cmd_args = [str(cmake_path), "--build", str(build_dir2), "--config", config]

        build_tool_args = []
        if num_parallel_jobs != 1:
            if is_windows() and args.cmake_generator != "Ninja" and not args.build_wasm:
                build_tool_args += [
                    "/maxcpucount:{}".format(num_parallel_jobs),
                    # if nodeReuse is true, msbuild processes will stay around for a bit after the build completes
                    "/nodeReuse:False",
                ]
            elif is_macOS() and args.use_xcode:
                # CMake will generate correct build tool args for Xcode
                cmd_args += ["--parallel", str(num_parallel_jobs)]
            else:
                build_tool_args += ["-j{}".format(num_parallel_jobs)]

        if build_tool_args:
            cmd_args += ["--"]
            cmd_args += build_tool_args

        _run_subprocess(cmd_args, env=env)


def _run_python_tests():
    # TODO: Run the python tests in /python
    pass


def _run_android_tests(args, build_dir: Path, config: str, cwd: Path):
    # TODO: Setup running tests using Android simulator and adb. See ORT build.py for example.
    source_dir = REPO_DIR
    pass


def _run_ios_tests(args, config: str, cwd: Path):
    # TODO: Setup running tests using xcode an iPhone simulator. See ORT build.py for example.
    source_dir = REPO_DIR
    pass


def _run_cxx_tests(args, build_dir: Path, configs: Set[str]):
    ctest_path = None if not args.ctest_path else _resolve_executable_path(args.ctest_path)

    for config in configs:
        log.info("Running tests for %s configuration", config)

        cwd = _get_build_config_dir(build_dir, config)

        if args.android:
            _run_android_tests(args, build_dir, config, cwd)
            continue
        elif args.ios:
            _run_ios_tests(args, config, cwd)
            continue

        if ctest_path:
            ctest_cmd = [str(ctest_path), "--build-config", config, "--verbose", "--timeout", "10800"]
            _run_subprocess(ctest_cmd, cwd=cwd)

        else:
            if is_windows():
                # Get the "Google Test Adapter" for vstest.
                if not (cwd / "GoogleTestAdapter.0.18.0").is_dir():
                    _run_subprocess(
                        [
                            "nuget.exe",
                            "restore",
                            str(REPO_DIR / "test" / "packages.config"),
                            "-ConfigFile",
                            str(REPO_DIR / "test" / "NuGet.config"),
                            "-PackagesDirectory",
                            str(cwd),
                        ]
                    )

                # test exes are in the bin/<config> subdirectory of the build output dir
                # call resolve() to get the full path as we're going to execute in build_dir not cwd
                test_dir = (cwd / "bin" / config).resolve()
                adapter = (cwd / 'GoogleTestAdapter.0.18.0' / 'build' / '_common').resolve()

                executables = [
                    str(test_dir / "extensions_test.exe"),
                    str(test_dir / "ocos_test.exe")
                ]

                _run_subprocess(
                    [
                        "vstest.console.exe",  # must be in the PATH. run this script from a VS dev shell.
                        "--parallel",
                        f"--TestAdapterPath:{str(adapter)}",
                        "/Logger:trx",
                        "/Enablecodecoverage",
                        "/Platform:x64",
                        f"/Settings:{str(REPO_DIR / 'test' / 'codeconv.runsettings')}",
                    ]
                    + executables,
                    cwd=build_dir,
                )

            else:
                executables = ["extensions_test", "ocos_test"]
                for exe in executables:
                    _run_subprocess([str(cwd / exe)], cwd=cwd)


def main():
    log.debug("Command line arguments:\n  {}".format(" ".join(shlex.quote(arg) for arg in sys.argv[1:])))

    args = _parse_arguments()
    cmake_extra_defines = _flatten_arg_list(args.cmake_extra_defines)
    cross_compiling = args.arm or args.arm64 or args.arm64ec or args.android

    # If there was no explicit argument saying what to do, default
    # to update, build and test (for native builds).
    if not (args.update or args.clean or args.build or args.test):
        log.debug("Defaulting to running update, build [and test for native builds].")
        args.update = True
        args.build = True
        if cross_compiling:
            args.test = args.android_abi == "x86_64" or args.android_abi == "arm64-v8a"
        else:
            args.test = True

    if args.skip_tests:
        args.test = False

    if args.build_wasm_static_lib:
        args.build_wasm = True

    if args.build_wasm:
        if not args.disable_wasm_exception_catching and args.disable_exceptions:
            # When '--disable_exceptions' is set, we set '--disable_wasm_exception_catching' as well
            args.disable_wasm_exception_catching = True
        if args.test and args.disable_wasm_exception_catching and not args.minimal_build:
            raise UsageError("WebAssembly tests need exception catching enabled to run if it's not minimal build")

    if args.android and is_windows():
        if args.cmake_generator != "Ninja":
            log.info("Setting cmake_generator to Ninja, which is required when cross-compiling Android on Windows.")
            args.cmake_generator = "Ninja"

    configs = set(args.config)

    # setup paths and directories
    # cmake_path can be None. For example, if a person only wants to run the tests, they don't need cmake.
    cmake_path = _resolve_executable_path(args.cmake_path)
    build_dir = args.build_dir

    if args.update or args.build:
        for config in configs:
            os.makedirs(_get_build_config_dir(build_dir, config), exist_ok=True)

    log.info("Build started")

    if args.update:
        if _is_reduced_ops_build(args):
            log.info("Generating config for selected ops")
            _generate_selected_ops_config(args.include_ops_by_config)

        cmake_extra_args = []
        if not args.skip_submodule_sync:
            _update_submodules(REPO_DIR)

        if is_windows():
            cpu_arch = platform.architecture()[0]
            if args.build_wasm:
                cmake_extra_args = ["-G", "Ninja"]
            elif args.cmake_generator == "Ninja":
                if cpu_arch == "32bit" or args.arm or args.arm64 or args.arm64ec:
                    raise UsageError(
                        "To cross-compile with Ninja, load the toolset environment for the target processor "
                        "(e.g. Cross Tools Command Prompt for VS)")
                cmake_extra_args = ["-G", args.cmake_generator]
            elif args.arm or args.arm64 or args.arm64ec:
                # Cross-compiling for ARM(64) architecture
                if args.arm:
                    cmake_extra_args = ["-A", "ARM"]
                elif args.arm64:
                    cmake_extra_args = ["-A", "ARM64"]
                elif args.arm64ec:
                    cmake_extra_args = ["-A", "ARM64EC"]
                cmake_extra_args += ["-G", args.cmake_generator]

                # Cannot test on host build machine for cross-compiled
                # builds (Override any user-defined behaviour for test if any)
                if args.test:
                    log.warning("Cannot test on host build machine for cross-compiled ARM(64) builds. "
                                "Will skip test running after build.")
                    args.test = False
            elif cpu_arch == "32bit" or args.x86:
                cmake_extra_args = ["-A", "Win32", "-T", "host=x64", "-G", args.cmake_generator]
            else:
                toolset = "host=x64"

                # TODO: Do we need the ability to specify the toolset?
                # if args.msvc_toolset:
                #     toolset += f",version={args.msvc_toolset}"

                cmake_extra_args = ["-A", "x64", "-T", toolset, "-G", args.cmake_generator]
        elif args.cmake_generator is not None and not (is_macOS() and args.use_xcode):
            cmake_extra_args += ["-G", args.cmake_generator]
        elif is_macOS():
            if args.use_xcode:
                cmake_extra_args += ["-G", "Xcode"]
            if not args.ios and not args.android and args.osx_arch == "arm64" and platform.machine() == "x86_64":
                if args.test:
                    log.warning("Cannot test ARM64 build on X86_64. Will skip test running after build.")
                    args.test = False

        if args.build_wasm:
            emsdk_version = args.emsdk_version
            emsdk_dir = REPO_DIR / "cmake" / "external" / "emsdk"
            emsdk_file = emsdk_dir / "emsdk.bat" if is_windows() else emsdk_dir / "emsdk"

            log.info("Installing emsdk...")
            _run_subprocess([emsdk_file, "install", emsdk_version], cwd=emsdk_dir)
            log.info("Activating emsdk...")
            _run_subprocess([emsdk_file, "activate", emsdk_version], cwd=emsdk_dir)

        _generate_build_tree(
            cmake_path,
            REPO_DIR,
            build_dir,
            configs,
            cmake_extra_defines,
            args,
            cmake_extra_args)

    if args.clean:
        clean_targets(cmake_path, build_dir, configs)

    if args.build:
        if args.parallel < 0:
            raise UsageError("Invalid parallel job count: {}".format(args.parallel))
        num_parallel_jobs = os.cpu_count() if args.parallel == 0 else args.parallel
        build_targets(args, cmake_path, build_dir, configs, num_parallel_jobs)

    if args.test:
        _run_python_tests()

        if args.enable_unit_tests:
            _validate_unit_test_args(args)
            _run_cxx_tests(args, build_dir, configs)

    log.info("Build complete")


if __name__ == "__main__":
    try:
        main()
    except UsageError as e:
        log.error(str(e))
        sys.exit(1)
