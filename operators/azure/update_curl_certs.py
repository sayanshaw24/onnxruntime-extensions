# save latest from https://curl.se/docs/caextract.html to a local pem file
file = "curl.cacert-2023-05-30.pem"

# strip out everything except the certs as per https://curl.se/libcurl/c/cacertinmem.html example.
# we create a .inc file that defines a char array with the contents to #include in c++ code
with (open("curl.cacert.pem.inc", "w") as out):
    out.write("static const char curl_pem[] = \n")
    in_cert = False
    num_certs = 0
    with (open(file, "r") as pem_input):
        for line in pem_input.readlines():
            if not in_cert:
                in_cert = "-----BEGIN CERTIFICATE-----" in line
                if in_cert:
                    num_certs += 1

            if in_cert:
                # write line with quoted text + \n
                # indent each line by 2
                out.write(f'  "{line.strip()}\\n"\n')
                in_cert = "-----END CERTIFICATE-----" not in line

    out.write(";")

    assert(num_certs > 0)
    assert(not in_cert)  # mismatched begin/end if not false
    print(f"Processed {num_certs}")

