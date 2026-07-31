#include "kvs_master/aws_env.hpp"

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace txing::board::kvs_master {
namespace {

using IniSections = std::unordered_map<std::string, std::unordered_map<std::string, std::string>>;

std::string Trim(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return {};
    }
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

IniSections ParseIniSections(const std::string& content) {
    IniSections sections;
    std::string current_section;
    std::istringstream stream(content);
    std::string raw_line;

    while (std::getline(stream, raw_line)) {
        const auto line = Trim(raw_line);
        if (line.empty() || line[0] == '#' || line[0] == ';') {
            continue;
        }
        if (line.front() == '[' && line.back() == ']') {
            current_section = Trim(line.substr(1, line.size() - 2));
            sections.try_emplace(current_section);
            continue;
        }

        const auto equals = line.find('=');
        if (equals == std::string::npos || current_section.empty()) {
            continue;
        }

        sections[current_section][Trim(line.substr(0, equals))] = Trim(line.substr(equals + 1));
    }

    return sections;
}

std::filesystem::path SharedCredentialsPath(const EnvLookup& lookup_env) {
    if (const auto explicit_path = lookup_env("AWS_SHARED_CREDENTIALS_FILE"); explicit_path && !explicit_path->empty()) {
        return *explicit_path;
    }

    if (const auto home = lookup_env("HOME"); home && !home->empty()) {
        return std::filesystem::path(*home) / ".aws" / "credentials";
    }

    throw std::runtime_error("could not determine the shared AWS credentials file path");
}

std::optional<AwsCredentials> LoadFromEnvironment(const EnvLookup& lookup_env) {
    const auto access_key_id = lookup_env("AWS_ACCESS_KEY_ID");
    const auto secret_access_key = lookup_env("AWS_SECRET_ACCESS_KEY");

    if (!access_key_id && !secret_access_key) {
        return std::nullopt;
    }
    if (!access_key_id || !secret_access_key || access_key_id->empty() || secret_access_key->empty()) {
        throw std::runtime_error(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must either both be set or both be absent"
        );
    }

    AwsCredentials credentials;
    credentials.access_key_id = Trim(*access_key_id);
    credentials.secret_access_key = Trim(*secret_access_key);

    if (const auto session_token = lookup_env("AWS_SESSION_TOKEN"); session_token) {
        const auto trimmed = Trim(*session_token);
        if (!trimmed.empty()) {
            credentials.session_token = trimmed;
        }
    }

    return credentials;
}

AwsCredentials LoadFromSharedCredentialsFile(const EnvLookup& lookup_env, const FileReader& read_file) {
    const auto profile = lookup_env("AWS_PROFILE").value_or("default");
    const auto path = SharedCredentialsPath(lookup_env);
    const auto content = read_file(path);
    const auto sections = ParseIniSections(content);
    const auto profile_it = sections.find(profile);
    if (profile_it == sections.end()) {
        throw std::runtime_error(
            "shared AWS credentials file " + path.string() + " does not contain the profile " + profile
        );
    }

    const auto& section = profile_it->second;
    const auto access_key_it = section.find("aws_access_key_id");
    const auto secret_access_key_it = section.find("aws_secret_access_key");
    if (access_key_it == section.end() || access_key_it->second.empty()) {
        throw std::runtime_error("profile " + profile + " is missing aws_access_key_id");
    }
    if (secret_access_key_it == section.end() || secret_access_key_it->second.empty()) {
        throw std::runtime_error("profile " + profile + " is missing aws_secret_access_key");
    }

    AwsCredentials credentials;
    credentials.access_key_id = access_key_it->second;
    credentials.secret_access_key = secret_access_key_it->second;
    const auto session_token_it = section.find("aws_session_token");
    if (session_token_it != section.end() && !session_token_it->second.empty()) {
        credentials.session_token = session_token_it->second;
    }
    return credentials;
}

}  // namespace

AwsCredentials ResolveAwsCredentials(const EnvLookup& lookup_env, const FileReader& read_file) {
    if (const auto environment_credentials = LoadFromEnvironment(lookup_env)) {
        return *environment_credentials;
    }
    return LoadFromSharedCredentialsFile(lookup_env, read_file);
}

AwsCredentials ResolveAwsCredentials() {
    return ResolveAwsCredentials(ProcessEnvironmentLookup(), FilesystemReader());
}

FileReader FilesystemReader() {
    return [](const std::filesystem::path& path) {
        std::ifstream stream(path);
        if (!stream.is_open()) {
            throw std::runtime_error(
                "shared AWS credentials were not found in " + path.string() +
                " and no AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY environment variables were set"
            );
        }
        return std::string(
            std::istreambuf_iterator<char>(stream),
            std::istreambuf_iterator<char>()
        );
    };
}

}  // namespace txing::board::kvs_master
