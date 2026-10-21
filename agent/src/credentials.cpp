#include "agent/kvs.hpp"
#include <aws/core/utils/DateTime.h>
#include <sstream>
#include <stdexcept>

namespace txing::agent {
void check_kvs(STATUS status, const char* operation) {
    if (STATUS_SUCCEEDED(status)) return;
    std::ostringstream message; message << operation << ": KVS status 0x" << std::hex << status;
    throw std::runtime_error(message.str());
}
KvsRuntime::KvsRuntime() { check_kvs(initKvsWebRtc(), "initKvsWebRtc"); }
KvsRuntime::~KvsRuntime() { deinitKvsWebRtc(); }
Credentials::Credentials(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> source) : source_(std::move(source)) {
    if (!source_) throw std::invalid_argument("AWS credential provider required");
    getCredentialsFn = &Credentials::get;
}
Credentials::~Credentials() { if (current_) freeAwsCredentials(&current_); }
std::string Credentials::error() const { std::lock_guard<std::mutex> lock(mutex_); return error_; }
STATUS Credentials::get(PAwsCredentialProvider base, PAwsCredentials* output) noexcept {
    if (!base || !output) return STATUS_NULL_ARG;
    *output = nullptr;
    auto& self = *static_cast<Credentials*>(base);
    std::lock_guard<std::mutex> lock(self.mutex_);
    try {
        auto credentials = self.source_->GetAWSCredentials();
        const auto now = Aws::Utils::DateTime::Now();
        const auto expiration = credentials.GetExpiration();
        if (credentials.IsEmpty() || expiration <= now) {
            self.error_ = "AWS credentials missing or expired; check the selected SDK profile/provider";
            return STATUS_INVALID_OPERATION;
        }
        const auto key = credentials.GetAWSAccessKeyId();
        const auto secret = credentials.GetAWSSecretKey();
        const auto token = credentials.GetSessionToken();
        PAwsCredentials next = nullptr;
        auto status = createAwsCredentials(const_cast<PCHAR>(key.c_str()), 0,
            const_cast<PCHAR>(secret.c_str()), 0, token.empty() ? nullptr : const_cast<PCHAR>(token.c_str()), 0,
            static_cast<UINT64>(expiration.Millis()) * 10000, &next);
        if (STATUS_FAILED(status)) { self.error_ = "KVS credential allocation failed"; return status; }
        if (self.current_) freeAwsCredentials(&self.current_);
        self.current_ = next; self.error_.clear(); *output = next; return STATUS_SUCCESS;
    } catch (...) {
        self.error_ = "AWS credential provider failed; refresh or reauthenticate the selected provider";
        return STATUS_INVALID_OPERATION;
    }
}
}
