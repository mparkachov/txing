#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

struct Options {
  std::string chip_tool = "chip-tool";
  std::string storage_directory;
  std::string node_id;
  int temperature_endpoint = 1;
  int humidity_endpoint = 2;
  int pressure_endpoint = 3;
  int power_endpoint = 0;
  double interval_seconds = 30.0;
  bool once = false;
  std::string parse_sample;
};

struct Readings {
  double measured_temperature;
  double measured_pressure;
  double measured_humidity;
  int battery_mv;
};

std::string shell_quote(const std::string &value) {
  std::string quoted = "'";
  for (const char ch : value) {
    if (ch == '\'') {
      quoted += "'\\''";
    } else {
      quoted += ch;
    }
  }
  quoted += "'";
  return quoted;
}

std::string run_command(const std::string &command) {
  std::array<char, 256> buffer{};
  std::string output;
  FILE *pipe = popen(command.c_str(), "r");
  if (pipe == nullptr) {
    throw std::runtime_error("failed to run command");
  }
  while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
    output += buffer.data();
  }
  const int status = pclose(pipe);
  if (status != 0) {
    std::ostringstream message;
    message << "command exited with status " << status << ": " << command;
    throw std::runtime_error(message.str());
  }
  return output;
}

std::optional<double> parse_attribute_value(const std::string &output) {
  const std::regex data_pattern(R"(Data\s*=\s*(-?[0-9]+(?:\.[0-9]+)?))");
  const std::regex json_pattern(R"("value"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?))");
  std::smatch match;
  if (std::regex_search(output, match, json_pattern) && match.size() >= 2) {
    return std::stod(match[1].str());
  }
  if (std::regex_search(output, match, data_pattern) && match.size() >= 2) {
    return std::stod(match[1].str());
  }
  return std::nullopt;
}

std::string build_read_command(
    const Options &options,
    const std::string &cluster,
    const std::string &attribute,
    int endpoint) {
  std::ostringstream command;
  command << shell_quote(options.chip_tool) << ' '
          << cluster << " read " << attribute << ' '
          << shell_quote(options.node_id) << ' '
          << endpoint;
  if (!options.storage_directory.empty()) {
    command << " --storage-directory " << shell_quote(options.storage_directory);
  }
  return command.str();
}

double read_required(
    const Options &options,
    const std::string &cluster,
    const std::string &attribute,
    int endpoint) {
  const std::string output = run_command(build_read_command(options, cluster, attribute, endpoint));
  const std::optional<double> value = parse_attribute_value(output);
  if (!value.has_value()) {
    throw std::runtime_error("chip-tool output did not contain an attribute value");
  }
  return value.value();
}

Readings read_weather(const Options &options) {
  const double temperature_raw = read_required(
      options, "temperaturemeasurement", "measured-value", options.temperature_endpoint);
  const double pressure_raw = read_required(
      options, "pressuremeasurement", "measured-value", options.pressure_endpoint);
  const double humidity_raw = read_required(
      options, "relativehumiditymeasurement", "measured-value", options.humidity_endpoint);
  const double battery_raw = read_required(
      options, "powersource", "bat-voltage", options.power_endpoint);

  return Readings{
      .measured_temperature = temperature_raw / 100.0,
      .measured_pressure = pressure_raw / 10.0,
      .measured_humidity = humidity_raw / 100.0,
      .battery_mv = static_cast<int>(battery_raw),
  };
}

long long now_ms() {
  const auto now = std::chrono::system_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::milliseconds>(now).count();
}

void write_online_json(const Readings &readings) {
  std::cout << "{\"status\":\"online\""
            << ",\"observedAtMs\":" << now_ms()
            << ",\"batteryMv\":" << readings.battery_mv
            << ",\"measuredTemperature\":" << readings.measured_temperature
            << ",\"measuredPressure\":" << readings.measured_pressure
            << ",\"measuredHumidity\":" << readings.measured_humidity
            << "}" << std::endl;
}

std::string json_escape(const std::string &value) {
  std::string escaped;
  for (const char ch : value) {
    switch (ch) {
      case '\\':
        escaped += "\\\\";
        break;
      case '"':
        escaped += "\\\"";
        break;
      case '\n':
        escaped += "\\n";
        break;
      case '\r':
        escaped += "\\r";
        break;
      case '\t':
        escaped += "\\t";
        break;
      default:
        escaped += ch;
        break;
    }
  }
  return escaped;
}

void write_offline_json(const std::string &error) {
  std::cout << "{\"status\":\"offline\""
            << ",\"observedAtMs\":" << now_ms()
            << ",\"error\":\"" << json_escape(error) << "\""
            << "}" << std::endl;
}

void print_usage() {
  std::cerr
      << "usage: weather-matter-watch --node-id NODE [--chip-tool PATH] [--once]\n"
      << "       weather-matter-watch --parse-sample 'Data = 2163'\n";
}

Options parse_options(int argc, char **argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string arg = argv[index];
    auto require_value = [&](const std::string &name) -> std::string {
      if (index + 1 >= argc) {
        throw std::runtime_error("missing value for " + name);
      }
      ++index;
      return argv[index];
    };
    if (arg == "--chip-tool") {
      options.chip_tool = require_value(arg);
    } else if (arg == "--storage-directory") {
      options.storage_directory = require_value(arg);
    } else if (arg == "--node-id") {
      options.node_id = require_value(arg);
    } else if (arg == "--temperature-endpoint") {
      options.temperature_endpoint = std::stoi(require_value(arg));
    } else if (arg == "--humidity-endpoint") {
      options.humidity_endpoint = std::stoi(require_value(arg));
    } else if (arg == "--pressure-endpoint") {
      options.pressure_endpoint = std::stoi(require_value(arg));
    } else if (arg == "--power-endpoint") {
      options.power_endpoint = std::stoi(require_value(arg));
    } else if (arg == "--interval") {
      options.interval_seconds = std::stod(require_value(arg));
    } else if (arg == "--once") {
      options.once = true;
    } else if (arg == "--parse-sample") {
      options.parse_sample = require_value(arg);
    } else if (arg == "--help" || arg == "-h") {
      print_usage();
      std::exit(0);
    } else {
      throw std::runtime_error("unknown option " + arg);
    }
  }
  return options;
}

}  // namespace

int main(int argc, char **argv) {
  try {
    const Options options = parse_options(argc, argv);
    if (!options.parse_sample.empty()) {
      const std::optional<double> value = parse_attribute_value(options.parse_sample);
      if (!value.has_value()) {
        std::cerr << "sample did not contain a parseable value\n";
        return 1;
      }
      std::cout << "{\"value\":" << value.value() << "}" << std::endl;
      return 0;
    }
    if (options.node_id.empty()) {
      print_usage();
      return 2;
    }

    while (true) {
      try {
        write_online_json(read_weather(options));
      } catch (const std::exception &error) {
        write_offline_json(error.what());
      }
      if (options.once) {
        return 0;
      }
      std::this_thread::sleep_for(
          std::chrono::milliseconds(static_cast<int>(options.interval_seconds * 1000.0)));
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
