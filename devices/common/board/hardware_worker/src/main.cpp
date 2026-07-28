#include "hardware_worker/config.hpp"
#include "hardware_worker/motor.hpp"
#include "hardware_worker/version.hpp"
#include "hardware_worker/proto_binding.hpp"

#include <grpcpp/grpcpp.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <filesystem>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace hw = txing::board::hardware_worker;
namespace board_hw_pb = ::txing::board::proto::hardware_v1;

namespace {

std::atomic_bool g_shutdown_requested{false};

void HandleSignal(int) {
    g_shutdown_requested.store(true);
}

board_hw_pb::MotionState ToProto(const hw::MotionState& motion) {
    board_hw_pb::MotionState out;
    out.set_left_speed(motion.left_speed);
    out.set_right_speed(motion.right_speed);
    out.set_sequence(motion.sequence);
    return out;
}

board_hw_pb::HardwareState ToProto(hw::HardwareState state) {
    switch (state) {
        case hw::HardwareState::Starting:
            return board_hw_pb::STARTING;
        case hw::HardwareState::Ready:
            return board_hw_pb::READY;
        case hw::HardwareState::Degraded:
            return board_hw_pb::DEGRADED;
        case hw::HardwareState::Error:
            return board_hw_pb::ERROR;
        case hw::HardwareState::Stopped:
            return board_hw_pb::STOPPED;
    }
    return board_hw_pb::HARDWARE_STATE_UNSPECIFIED;
}

board_hw_pb::HardwareStatus ToProto(const hw::HardwareStatus& status) {
    board_hw_pb::HardwareStatus out;
    out.set_state(ToProto(status.state));
    out.set_actuator_ready(status.actuator_ready);
    out.set_last_error(status.last_error);
    *out.mutable_motion() = ToProto(status.motion);
    if (status.active_deadline_unix_ms.has_value()) {
        out.set_active_deadline_unix_ms(*status.active_deadline_unix_ms);
    }
    out.set_worker_version(hw::kTxingBoardHardwareWorkerVersion);
    return out;
}

hw::Vector3 FromProto(const board_hw_pb::Vector3& value) {
    hw::Vector3 out;
    out.x = value.x();
    out.y = value.y();
    out.z = value.z();
    return out;
}

hw::Twist FromProto(const board_hw_pb::Twist& twist) {
    hw::Twist out;
    out.linear = FromProto(twist.linear());
    out.angular = FromProto(twist.angular());
    return out;
}

class HardwareService final : public board_hw_pb::BoardHardware::Service {
public:
    explicit HardwareService(hw::MotorController controller) : controller_(std::move(controller)) {}

    grpc::Status GetStatus(grpc::ServerContext*, const board_hw_pb::GetStatusRequest*, board_hw_pb::HardwareStatus* response) override {
        std::lock_guard<std::mutex> lock(mutex_);
        *response = ToProto(controller_.Status());
        return grpc::Status::OK;
    }

    grpc::Status ApplyVelocity(
        grpc::ServerContext*,
        const board_hw_pb::ApplyVelocityRequest* request,
        board_hw_pb::ApplyVelocityResponse* response
    ) override {
        std::lock_guard<std::mutex> lock(mutex_);
        try {
            const auto motion = controller_.ApplyVelocity(
                FromProto(request->twist()),
                request->deadline_unix_ms(),
                hw::NowUnixMs()
            );
            *response->mutable_motion() = ToProto(motion);
            *response->mutable_status() = ToProto(controller_.Status());
            return grpc::Status::OK;
        } catch (const std::exception& err) {
            return grpc::Status(grpc::StatusCode::FAILED_PRECONDITION, err.what());
        }
    }

    grpc::Status Stop(grpc::ServerContext*, const board_hw_pb::StopRequest*, board_hw_pb::StopResponse* response) override {
        std::lock_guard<std::mutex> lock(mutex_);
        try {
            const auto motion = controller_.Stop(true);
            *response->mutable_motion() = ToProto(motion);
            *response->mutable_status() = ToProto(controller_.Status());
            return grpc::Status::OK;
        } catch (const std::exception& err) {
            return grpc::Status(grpc::StatusCode::INTERNAL, err.what());
        }
    }

    bool Tick() {
        std::lock_guard<std::mutex> lock(mutex_);
        try {
            return controller_.Tick(hw::NowUnixMs());
        } catch (const std::exception& err) {
            std::cerr << "WARN hardware worker watchdog stop failed: " << err.what() << "\n";
            return false;
        }
    }

    void Shutdown() {
        std::lock_guard<std::mutex> lock(mutex_);
        controller_.Close();
    }

private:
    std::mutex mutex_;
    hw::MotorController controller_;
};

void PrepareSocketPath(const std::string& socket_path) {
    const std::filesystem::path path(socket_path);
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::error_code err;
    std::filesystem::remove(path, err);
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto parsed = hw::ParseCli(argc, argv, hw::ProcessEnvironmentLookup());
        if (parsed.show_help) {
            std::cout << hw::UsageText();
            return 0;
        }
        if (parsed.show_version) {
            std::cout << TXING_BOARD_HARDWARE_WORKER_BINARY_NAME " "
                      << hw::kTxingBoardHardwareWorkerVersion
                      << "\n";
            return 0;
        }

        std::signal(SIGINT, HandleSignal);
        std::signal(SIGTERM, HandleSignal);

        PrepareSocketPath(parsed.config.socket_path);
        HardwareService service(hw::MotorController::FromConfig(parsed.config.motor));

        grpc::ServerBuilder builder;
        builder.AddListeningPort("unix:" + parsed.config.socket_path, grpc::InsecureServerCredentials());
        builder.RegisterService(&service);
        auto server = builder.BuildAndStart();
        if (!server) {
            throw std::runtime_error("failed to start BoardHardware gRPC server");
        }

        std::cout << "INFO " TXING_BOARD_HARDWARE_WORKER_BINARY_NAME " started version="
                  << hw::kTxingBoardHardwareWorkerVersion
                  << " socket=" << parsed.config.socket_path << "\n";

        std::thread server_thread([&server]() {
            server->Wait();
        });

        while (!g_shutdown_requested.load()) {
            service.Tick();
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        std::cout << "INFO " TXING_BOARD_HARDWARE_WORKER_BINARY_NAME " shutdown requested\n";
        service.Shutdown();
        server->Shutdown();
        if (server_thread.joinable()) {
            server_thread.join();
        }
        std::error_code err;
        std::filesystem::remove(parsed.config.socket_path, err);
        return 0;
    } catch (const std::exception& err) {
        std::cerr << "ERROR " TXING_BOARD_HARDWARE_WORKER_BINARY_NAME ": " << err.what() << "\n";
        return 1;
    }
}
