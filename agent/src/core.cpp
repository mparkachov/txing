#include "agent/core.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <algorithm>
#include <stdexcept>

namespace txing::agent {
using namespace std::chrono_literals;
using Aws::Utils::Json::JsonValue;

Profile profile(const std::string& type, const std::string& thing,
                const std::string& region, const std::string& ca) {
    if (type != "tbot") throw std::runtime_error("unsupported registered Thing type: " + type);
    if (thing.empty() || region.empty() || ca.empty()) throw std::invalid_argument("Thing, region and CA path are required");
    return {{thing + "-mavlink", region, "txing.mavlink.v1", ca, Media::data, Role::viewer},
            {thing + "-board-video", region, "", ca, Media::h264, Role::viewer}};
}

bool valid_mavlink2(const Bytes& b) {
    // Preserve unknown dialects, CRC bytes, IDs and signatures exactly.
    return b.size() >= 12 && b[0] == 0xfd && (b[2] & ~1u) == 0 &&
           b.size() == 12u + b[1] + ((b[2] & 1u) ? 13u : 0u);
}

Session::Session(Profile p, TransportFactory f, Operator& op, Time now)
    : profile_(std::move(p)), factory_(std::move(f)), operator_(op), last_verified_(now) {
    telemetry_.config = profile_.telemetry;
    video_.config = profile_.video;
    observation_thread_ = std::thread([this] {
        while (true) {
            auto event = events_.pop();
            if (!event) event = observations_.pop();
            if (!event) {
                if (delivery_stopped_) break;
                std::this_thread::sleep_for(1ms); continue;
            }
            try {
                switch (event->kind) {
                    case Observation::telemetry: operator_.telemetry(event->bytes); break;
                    case Observation::connection: operator_.connection(event->stream, event->state, event->detail); break;
                    case Observation::control: operator_.control(event->held, event->detail); break;
                }
            } catch (...) { response_overflow_ = true; }
        }
    });
    try {
        video_thread_ = std::thread([this] {
            while (auto frame = videos_.pop(true)) {
                try { operator_.video(*frame); } catch (...) { response_overflow_ = true; }
            }
        });
    } catch (...) {
        delivery_stopped_ = true; observations_.close(); events_.close(); observation_thread_.join(); throw;
    }
}

Session::~Session() {
    shutdown("process shutdown");
    // Join transport callbacks while their queues and consumers still exist.
    telemetry_.retiring.reset(); video_.retiring.reset();
    delivery_stopped_ = true; observations_.close(); events_.close(); videos_.close();
    if (observation_thread_.joinable()) observation_thread_.join();
    if (video_thread_.joinable()) video_thread_.join();
}

void Session::verified(Lifecycle state, Time now) {
    if (stopped_) return;
    lifecycle_ = state; has_verification_ = true; last_verified_ = now;
}

bool Session::enqueue(Command command) {
    std::lock_guard<std::mutex> lock(commands_mutex_);
    if (commands_.size() == 64) return false;
    commands_.push_back(std::move(command)); return true;
}
bool Session::acquire(std::string actor) {
    if (actor.empty() || actor.size() > 256) return false;
    return enqueue({Command::acquire, {}, std::move(actor)});
}
bool Session::send(Bytes bytes) {
    if (!valid_mavlink2(bytes)) return false;
    const auto generation = authorized_generation_.load();
    if (!generation) return false;
    return enqueue({Command::send, std::move(bytes), {}, generation});
}
void Session::release() {
    if (!enqueue({Command::release, {}, {}})) response_overflow_ = true;
}
void Session::client_activity() {
    if (!enqueue({Command::activity, {}, {}})) response_overflow_ = true;
}

void Session::emit_control(bool held, const std::string& reason) {
    Observation event{}; event.kind = Observation::control; event.held = held; event.detail = reason;
    const auto dropped = events_.dropped();
    events_.push(std::move(event), reason.size() + 64);
    if (events_.dropped() != dropped) response_overflow_ = true;
}
bool Session::text(const std::string& s) {
    return telemetry_.transport && telemetry_.transport->state() == Connection::connected &&
           telemetry_.transport->send(Bytes(s.begin(), s.end()), false);
}
void Session::request(const std::string& type, const std::string& actor, Time now) {
    pending_type_ = type; pending_id_ = "agent-" + std::to_string(++sequence_); request_at_ = now;
    JsonValue request;
    request.WithString("type", type.c_str()).WithString("requestId", pending_id_.c_str());
    if (type == "control.activate") request.WithString("actor", actor.c_str()).WithBool("takeover", false);
    else request.WithInt64("epoch", static_cast<long long>(epoch_));
    if (!text(request.View().WriteCompact().c_str())) lose("control request send failed");
}
void Session::lose(const std::string& reason, bool release_lease) {
    authorized_generation_ = 0;
    const bool was_authorized = held_ || !pending_id_.empty();
    if (held_ && release_lease) {
        JsonValue release;
        release.WithString("type", "control.release_active")
               .WithString("requestId", ("release-" + std::to_string(++sequence_)).c_str())
               .WithInt64("epoch", static_cast<long long>(epoch_));
        text(release.View().WriteCompact().c_str());
    }
    held_ = false; pending_id_.clear(); pending_type_.clear(); session_id_.clear();
    if (was_authorized) emit_control(false, reason);
}

void Session::response(const std::string& payload, Time now) {
    JsonValue json(Aws::String(payload.c_str()));
    if (!json.WasParseSuccessful()) { lose("invalid control JSON"); return; }
    auto view = json.View();
    if (!view.IsObject() || !view.ValueExists("type") || !view.GetObject("type").IsString()) return;
    const auto type = view.GetString("type");
    const bool matching = view.ValueExists("requestId") && view.GetObject("requestId").IsString() &&
                          view.GetString("requestId") == pending_id_.c_str();
    if (type == "control.error") {
        if (matching) lose(view.ValueExists("code") && view.GetObject("code").IsString()
                           ? view.GetString("code").c_str() : "control error");
        return;
    }
    if (!view.ValueExists("state") || !view.GetObject("state").IsObject()) return;
    auto state = view.GetObject("state");
    if (!state.ValueExists("leaseTtlMs") || !state.GetObject("leaseTtlMs").IsIntegerType() ||
        state.GetInt64("leaseTtlMs") != 5000 || !state.ValueExists("epoch") ||
        !state.GetObject("epoch").IsIntegerType() || state.GetInt64("epoch") < 0 ||
        !state.ValueExists("activeControl")) { lose("invalid lease state"); return; }
    auto active = state.GetObject("activeControl");
    const bool valid = active.IsObject() && active.ValueExists("sessionId") &&
        active.GetObject("sessionId").IsString() && !active.GetString("sessionId").empty() &&
        active.ValueExists("epoch") && active.GetObject("epoch").IsIntegerType() &&
        active.GetInt64("epoch") >= 0 && active.GetInt64("epoch") == state.GetInt64("epoch");
    if (held_ && (!valid || active.GetString("sessionId") != session_id_.c_str() ||
                  static_cast<std::uint64_t>(active.GetInt64("epoch")) != epoch_)) {
        lose("board control ownership changed", false); return;
    }
    if (!matching) return;
    if (pending_type_ == "control.activate" && type == "control.activated" && valid) {
        session_id_ = active.GetString("sessionId").c_str();
        epoch_ = static_cast<std::uint64_t>(active.GetInt64("epoch"));
        held_ = true; last_renewed_ = now; next_renew_ = now + 1s;
        authorized_generation_ = ++control_generation_;
        pending_id_.clear(); pending_type_.clear(); emit_control(true, "acquired");
    } else if (pending_type_ == "control.renew_active" && type == "control.renewed" && held_) {
        last_renewed_ = now; next_renew_ = now + 1s; pending_id_.clear(); pending_type_.clear();
    } else lose("unexpected control response");
}

void Session::update(Link& link, Stream stream, bool wanted, Time now) {
    if (link.retiring && link.retiring->finished()) link.retiring.reset();
    if (!wanted && link.transport) {
        if (stream == Stream::telemetry) lose("telemetry stopped");
        *link.accepting = false;
        link.transport->stop(); link.retiring = std::move(link.transport); link.backoff = 1;
    }
    auto state = link.transport ? link.transport->state() : Connection::stopped;
    if (link.transport && (state == Connection::failed ||
        (state == Connection::connecting && now - link.attempted >= 20s))) {
        link.last_error = link.transport->error();
        if (state == Connection::connecting) {
            link.last_error = "peer negotiation exceeded 20 seconds" +
                (link.last_error.empty() ? std::string{} : ": " + link.last_error);
        } else if (link.last_error.empty()) link.last_error = "transport failed";
        if (stream == Stream::telemetry) lose("telemetry connection lost");
        *link.accepting = false;
        link.transport->stop(); link.retiring = std::move(link.transport);
        link.retry_at = now + std::chrono::seconds(link.backoff);
        link.backoff = std::min(10, link.backoff * 2); state = Connection::failed;
    }
    if (wanted && !link.transport && !link.retiring && now >= link.retry_at) {
        link.transport = factory_(); link.attempted = now;
        link.accepting = std::make_shared<std::atomic<bool>>(true);
        auto accepting = link.accepting;
        TransportEvents events;
        events.data = [this, accepting](Bytes bytes, bool binary) {
            if (!*accepting) return;
            if (binary) {
                if (!valid_mavlink2(bytes)) return;
                const auto size = bytes.size();
                Observation e{}; e.kind = Observation::telemetry; e.bytes = std::move(bytes);
                observations_.push(std::move(e), size + 64);
            } else if (bytes.size() <= 4096) {
                const auto before = responses_.dropped();
                responses_.push(std::string(bytes.begin(), bytes.end()), bytes.size());
                if (before != responses_.dropped()) response_overflow_ = true;
            } else response_overflow_ = true;
        };
        events.video = [this, accepting](EncodedVideo frame) {
            if (!*accepting) return;
            auto size = frame.bytes.size(); videos_.push(std::move(frame), size);
        };
        try { link.transport->start(link.config, std::move(events)); state = link.transport->state(); }
        catch (const std::exception& e) {
            link.last_error = e.what(); *link.accepting = false;
            link.transport->stop(); link.retiring = std::move(link.transport);
            link.retry_at = now + std::chrono::seconds(link.backoff);
            link.backoff = std::min(10, link.backoff * 2); state = Connection::failed;
        }
    }
    if (state == Connection::connected) { link.backoff = 1; link.last_error.clear(); }
    if (state != link.previous) {
        Observation e{}; e.kind = Observation::connection; e.stream = stream;
        e.state = state; e.detail = link.last_error;
        const auto dropped = events_.dropped();
        events_.push(std::move(e), link.last_error.size() + 64); link.previous = state;
        if (events_.dropped() != dropped) response_overflow_ = true;
    }
}

bool Session::tick(Time now) {
    if (stopped_) return false;
    if (now - last_verified_ >= 15s) { shutdown("lifecycle unverified for 15 seconds"); return false; }
    if (has_verification_ && (!lifecycle_.born || lifecycle_.redcon < 1 || lifecycle_.redcon > 2)) {
        shutdown("device inactive or dead"); return false;
    }
    update(telemetry_, Stream::telemetry, has_verification_, now);
    update(video_, Stream::video, has_verification_ && lifecycle_.redcon == 1, now);
    if (response_overflow_.exchange(false)) lose("operator exception or control response overload");
    // Process current responses before queued operator actions. All authority
    // mutation is confined to this hosting thread.
    while (auto reply = responses_.pop()) response(*reply, now);
    if (held_ && (now - last_client_ >= 5s || now - last_renewed_ >= 5s)) lose("client inactivity or lease expiry");
    if (!pending_id_.empty() && now - request_at_ >= 3s) lose("control request timed out");
    std::deque<Command> commands;
    { std::lock_guard<std::mutex> lock(commands_mutex_); commands.swap(commands_); }
    for (auto& c : commands) {
        switch (c.kind) {
            case Command::activity: last_client_ = now; break;
            case Command::release: lose("operator released"); break;
            case Command::acquire:
                if (held_) break;
                if (pending_id_.empty() && telemetry_.transport &&
                    telemetry_.transport->state() == Connection::connected) {
                    last_client_ = now; request("control.activate", c.actor, now);
                } else emit_control(false, "control unavailable");
                break;
            case Command::send:
                if (!held_ || c.authority_generation != authorized_generation_.load()) break;
                if (held_ && telemetry_.transport && telemetry_.transport->send(c.bytes, true)) last_client_ = now;
                else if (held_) lose("MAVLink send failed");
                break;
        }
    }
    if (held_ && pending_id_.empty() && now >= next_renew_) request("control.renew_active", "", now);
    return true;
}

void Session::shutdown(const std::string& reason) {
    if (stopped_) return;
    stopped_ = true; stop_reason_ = reason; lose(reason);
    for (auto* link : {&telemetry_, &video_}) {
        if (link->transport) {
            *link->accepting = false;
            link->transport->stop(); link->retiring = std::move(link->transport);
        }
    }
}
}
