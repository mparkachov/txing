#include "txing_board_kvs_master/config.hpp"
#include "txing_board_kvs_master/markers.hpp"
#include "txing_board_kvs_master/runtime.hpp"

#include <exception>
#include <iostream>

int main(int argc, char** argv) {
    try {
        const auto parsed = txing::board::kvs_master::ParseCli(
            argc,
            argv,
            txing::board::kvs_master::ProcessEnvironmentLookup()
        );
        if (parsed.show_help) {
            std::cout << txing::board::kvs_master::UsageText();
            return 0;
        }

        txing::board::kvs_master::Run(parsed.config);
        return 0;
    } catch (const std::exception& error) {
        txing::board::kvs_master::EmitMarker(
            "TXING_KVS_ERROR",
            {{"detail", error.what()}}
        );
        return 1;
    }
}
