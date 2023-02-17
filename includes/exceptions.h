// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#pragma once

#include <iostream>
#include <stdexcept>

#include "onnxruntime_c_api.h"

namespace OrtW {
// All C++ methods that can fail will throw an exception of this type
struct Exception : std::exception {
  Exception(std::string&& string, OrtErrorCode code) : message_{std::move(string)}, code_{code} {}

  OrtErrorCode GetOrtErrorCode() const { return code_; }
  const char* what() const noexcept override { return message_.c_str(); }

 private:
  std::string message_;
  OrtErrorCode code_;
};

#ifdef OCOS_NO_EXCEPTIONS
#define ORTX_CXX_API_THROW(string, code)                            \
  do {                                                              \
    std::cerr << OrtW::Exception(string, code).what() << std::endl; \
    abort();                                                        \
  } while (false)

#define OCOS_TRY if (true)
#define OCOS_CATCH(x) else if (false)
#define OCOS_RETHROW
// In order to ignore the catch statement when a specific exception (not ... ) is caught and referred
// in the body of the catch statements, it is necessary to wrap the body of the catch statement into
// a lambda function. otherwise the exception referred will be undefined and cause build break
#define OCOS_HANDLE_EXCEPTION(func)
#else
#define ORTX_CXX_API_THROW(string, code) \
  throw OrtW::Exception(string, code)

#define OCOS_TRY try
#define OCOS_CATCH(x) catch (x)
#define OCOS_RETHROW throw;
#define OCOS_HANDLE_EXCEPTION(func) func()
#endif

inline void ThrowOnError(const OrtApi& ort, OrtStatus* status) {
  if (status) {
    std::string error_message = ort.GetErrorMessage(status);
    OrtErrorCode error_code = ort.GetErrorCode(status);
    ort.ReleaseStatus(status);
    ORTX_CXX_API_THROW(std::move(error_message), error_code);
  }
}
}  // namespace OrtW

// macros to wrap entry points that ORT calls where we may need to prevent exceptions propagating upwards to ORT
#define API_IMPL_BEGIN \
  OCOS_TRY {
// if we have to contain exceptions, log and abort().
#ifdef OCOS_CONTAIN_EXCEPTIONS
#define API_IMPL_END(funcname)                                               \
  }                                                                          \
  OCOS_CATCH(const std::exception& ex) {                                     \
    OCOS_HANDLE_EXCEPTION([&]() {                                            \
      std::cerr << "Exception in " << funcname << ": " << ex.what() << "\n"; \
      abort();                                                               \
    });                                                                      \
  }
#else
// rethrow. funcname is ignored in this case
#define API_IMPL_END(funcname)           \
  }                                      \
  OCOS_CATCH(const std::exception& ex) { \
    OCOS_HANDLE_EXCEPTION([&]() {        \
      OCOS_RETHROW;                      \
    });                                  \
  }
#endif
