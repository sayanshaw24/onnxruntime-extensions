// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#include "curl_invoker.hpp"

#include <sstream>

#if defined(__ANDROID__)
#define USE_IN_MEMORY_CURL_CERTS
#endif

#if defined(USE_IN_MEMORY_CURL_CERTS)
#include <openssl/err.h>
#include <openssl/ssl.h>
#endif

namespace ort_extensions {
namespace {
// need to do in memory cert on Android pending finding a way to use the system certs.
#if defined(USE_IN_MEMORY_CURL_CERTS)
// in-memory certs
CURLcode sslctx_function(CURL* /*curl*/, void* sslctx, void* /*parm*/) {
  // the #include defines `static const char curl_pem[] = ...;` with the certs
  #include "curl.cacert.pem.inc"

  // TODO: Doing this on every requests seems excessive. See if we can cache anything.
  BIO* cbio = BIO_new_mem_buf(curl_pem, sizeof(curl_pem));
  X509_STORE* cts = SSL_CTX_get_cert_store(static_cast<SSL_CTX*>(sslctx));

  CURLcode rv = CURLE_ABORTED_BY_CALLBACK;

  if (!cts || !cbio) {
    return rv;
  }

  STACK_OF(X509_INFO)* inf = PEM_X509_INFO_read_bio(cbio, NULL, NULL, NULL);

  if (!inf) {
    BIO_free(cbio);
    return rv;
  }

  for (int i = 0; i < sk_X509_INFO_num(inf); ++i) {
    X509_INFO* itmp = sk_X509_INFO_value(inf, i);
    if (itmp->x509) {
      X509_STORE_add_cert(cts, itmp->x509);
    }

    if (itmp->crl) {
      X509_STORE_add_crl(cts, itmp->crl);
    }
  }

  sk_X509_INFO_pop_free(inf, X509_INFO_free);
  BIO_free(cbio);

  rv = CURLE_OK;
  return rv;
}

#endif
}  // namespace

// apply the callback only when response is for sure to be a '/0' terminated string
size_t CurlHandler::WriteStringCallback(char* contents, size_t element_size, size_t num_elements, void* userdata) {
  try {
    size_t bytes = element_size * num_elements;
    std::string& buffer = *static_cast<std::string*>(userdata);
    buffer.append(contents, bytes);
    return bytes;
  } catch (const std::exception& ex) {
    // TODO: This should be captured/logger properly
    std::cerr << ex.what() << std::endl;
    return 0;
  } catch (...) {
    // exception caught, abort write
    std::cerr << "Unknown exception caught in CurlHandler::WriteStringCallback" << std::endl;
    return 0;
  }
}

CurlHandler::CurlHandler(WriteCallBack callback) : curl_(curl_easy_init(), curl_easy_cleanup),
                                                   headers_(nullptr, curl_slist_free_all),
                                                   from_holder_(from_, curl_formfree) {
  CURL* curl = curl_.get();  // CURL == void* so can't dereference

  curl_easy_setopt(curl, CURLOPT_BUFFERSIZE, 100 * 1024L);  // how was this size chosen? should it be set on a per operator basis?
  curl_easy_setopt(curl, CURLOPT_NOPROGRESS, 1L);
  curl_easy_setopt(curl, CURLOPT_USERAGENT, "curl/7.83.1");  // should this value come from the curl src instead of being hardcoded?
  curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 50L);            // 50 seems like a lot if we're directly calling a specific endpoint
  curl_easy_setopt(curl, CURLOPT_FTP_SKIP_PASV_IP, 1L);      // what does this have to do with http requests?
  curl_easy_setopt(curl, CURLOPT_TCP_KEEPALIVE, 1L);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, callback);

#if defined(USE_IN_MEMORY_CURL_CERTS)
  curl_easy_setopt(curl, CURLOPT_SSL_CTX_FUNCTION, sslctx_function);
#endif
  // should this be configured via a node attribute? different endpoints may have different timeouts
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 15);
}

////////////////////// CurlInvoker //////////////////////

CurlInvoker::CurlInvoker(const OrtApi& api, const OrtKernelInfo& info)
    : CloudBaseKernel(api, info) {
}

void CurlInvoker::ComputeImpl(const ortc::Variadic& inputs, ortc::Variadic& outputs) const {
  std::string auth_token = GetAuthToken(inputs);

  if (inputs.Size() != InputNames().size()) {
    ORTX_CXX_API_THROW("input count mismatch", ORT_RUNTIME_EXCEPTION);
  }

  // do any additional validation of the number and type of inputs/outputs
  ValidateInputs(inputs);

  // set the options for the curl handler that apply to all usages
  CurlHandler curl_handler(CurlHandler::WriteStringCallback);

  std::string full_auth = std::string{"Authorization: Bearer "} + auth_token;
  curl_handler.AddHeader(full_auth.c_str());
  curl_handler.SetOption(CURLOPT_URL, ModelUri().c_str());
  curl_handler.SetOption(CURLOPT_VERBOSE, Verbose());

  std::string response;
  curl_handler.SetOption(CURLOPT_WRITEDATA, (void*)&response);

  SetupRequest(curl_handler, inputs);
  ExecuteRequest(curl_handler);
  ProcessResponse(response, outputs);
}

void CurlInvoker::ExecuteRequest(CurlHandler& curl_handler) const {
  // this is where we could add any logic required to make the request async or maybe handle retries/cancellation.
  auto curl_ret = curl_handler.Perform();
  if (CURLE_OK != curl_ret) {
    const char* err = curl_easy_strerror(curl_ret);
    KERNEL_LOG(ORT_LOGGING_LEVEL_ERROR, ("Curl error (CURLcode=" + std::to_string(curl_ret) + "): " + err).c_str());

    ORTX_CXX_API_THROW(err, ORT_FAIL);
  }
}

}  // namespace ort_extensions
