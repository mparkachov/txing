#pragma once
namespace txing::agent {
int attach_main(int argc, char** argv);
#ifdef TXING_AGENT_TESTING
class ManualOperator;
// Test-only loopback transport; production CLI always requires managed TLS.
int test_attach_loopback(ManualOperator&, unsigned port, unsigned seconds, unsigned validation_port = 0);
#endif
}
