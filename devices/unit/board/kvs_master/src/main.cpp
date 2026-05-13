#include "kvs_master/config.hpp"
#include "kvs_master/markers.hpp"
#include "kvs_master/runtime.hpp"
#include "kvs_master/version.hpp"

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
        if (parsed.show_version) {
            std::cout << "txing-board-kvs-master "
                      << txing::board::kvs_master::kTxingBoardKvsMasterVersion
                      << '\n';
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
