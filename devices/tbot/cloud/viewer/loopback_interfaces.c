/* Test-only interface enumeration: the SDK ignores interfaces flagged LOOPBACK.
 * Expose localhost as the test interface so ICE/DTLS/SCTP/SRTP run over real
 * UDP without depending on VPNs, LAN routing, or an external TURN/signaling
 * server. This file is never linked into the production viewer.
 */
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <stdlib.h>

struct test_interface {
  struct ifaddrs interface;
  struct sockaddr_in address;
};
int getifaddrs(struct ifaddrs **out) {
  struct test_interface *entry = calloc(1, sizeof(*entry));
  if (!entry)
    return -1;
  entry->interface.ifa_name = "txing-test";
  entry->interface.ifa_flags = IFF_UP | IFF_RUNNING;
  entry->address.sin_family = AF_INET;
  entry->address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  entry->interface.ifa_addr = (struct sockaddr *)&entry->address;
  *out = &entry->interface;
  return 0;
}
void freeifaddrs(struct ifaddrs *entry) { free(entry); }
