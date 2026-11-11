FROM docker.io/library/golang:1.25-bookworm@sha256:83fb73a52c2b487af429f55789e3610142c8e8055abe0c2285b77f1541bcf519 AS go-build
WORKDIR /src
COPY devices/virtual-quad/qualification/supervisor/ ./
RUN CGO_ENABLED=0 go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/virtual-quad-qualification .

# The pinned KVS SDK uses lws_http_date_parse_unix, which Debian Bookworm's libwebsockets lacks.
FROM docker.io/library/debian:trixie-slim@sha256:24a01011d10eba3a023bc8585b9650b8b29021240d4217c05b905e09ef4a5232 AS native-build
ARG ARDUCOPTER_REV=fb773567896014da007bca58358704d4a0d8516f
ARG BUILD_JOBS=4
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates cmake curl git libcap-dev libcurl4-openssl-dev \
    libgstreamer-plugins-base1.0-dev liblog4cplus-dev libsrtp2-dev libssl-dev \
    libusrsctp-dev libwebsockets-dev ninja-build pkg-config python3 python3-dev \
    python3-empy python3-lxml python3-pexpect python3-setuptools \
    python3-yaml zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git init /ardupilot \
    && git -C /ardupilot remote add origin https://github.com/ArduPilot/ardupilot.git \
    && git -C /ardupilot fetch --depth 1 origin "${ARDUCOPTER_REV}" \
    && git -C /ardupilot checkout --detach FETCH_HEAD \
    && test "$(git -C /ardupilot rev-parse HEAD)" = "${ARDUCOPTER_REV}" \
    && git -C /ardupilot submodule update --init --recursive --depth 1
WORKDIR /ardupilot
RUN ./waf configure --board sitl && ./waf copter -j "${BUILD_JOBS}" \
    && mkdir /out \
    && strip -o /out/arducopter build/sitl/bin/arducopter \
    && { git rev-parse HEAD && git submodule status --recursive; } > /out/arducopter-source.txt \
    && dpkg-query -W > /out/build-packages.txt

WORKDIR /src
COPY devices/common/board/kvs_master devices/common/board/kvs_master
COPY devices/common/kvs devices/common/kvs
COPY devices/virtual-quad/qualification/CMakeLists.txt devices/virtual-quad/qualification/media.cpp devices/virtual-quad/qualification/
RUN cmake -S devices/virtual-quad/qualification -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DTXING_KVS_REAL_SDK=ON \
    && CMAKE_BUILD_PARALLEL_LEVEL="${BUILD_JOBS}" cmake --build /build --target virtual-quad-media \
    && strip -o /out/virtual-quad-media /build/virtual-quad-media

FROM docker.io/library/debian:trixie-slim@sha256:24a01011d10eba3a023bc8585b9650b8b29021240d4217c05b905e09ef4a5232 AS qualification-runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gstreamer1.0-plugins-bad gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-ugly gstreamer1.0-tools libcurl4t64 libgcc-s1 \
    liblog4cplus-2.0.5t64 libsrtp2-1 libssl3t64 libstdc++6 libusrsctp2 libwebsockets19t64 zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY --from=go-build /out/virtual-quad-qualification /opt/quad/bin/
COPY --from=native-build /out/arducopter /out/virtual-quad-media /opt/quad/bin/
COPY --from=native-build /out/arducopter-source.txt /out/build-packages.txt /ardupilot/COPYING.txt /opt/quad/evidence/
COPY devices/common/kvs/sdk.commit /opt/quad/evidence/kvs-sdk.commit
COPY devices/virtual-quad/qualification/qualification.parm /opt/quad/
RUN dpkg-query -W > /opt/quad/evidence/runtime-packages.txt
USER 10001:10001
ENV HOME=/tmp XDG_CACHE_HOME=/tmp
RUN test "$(uname -m)" = aarch64 \
    && test -r /etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem \
    && ldd /opt/quad/bin/arducopter /opt/quad/bin/virtual-quad-media > /tmp/dependencies.txt \
    && if grep -q 'not found' /tmp/dependencies.txt; then cat /tmp/dependencies.txt; exit 1; fi \
    && for plugin in videotestsrc x264enc h264parse appsink; do gst-inspect-1.0 "$plugin" >/dev/null || exit 1; done \
    && cat /tmp/dependencies.txt \
    && rm -f /tmp/dependencies.txt /tmp/gstreamer-1.0/registry.*
ENTRYPOINT ["/opt/quad/bin/virtual-quad-qualification"]
CMD ["kvs"]

FROM scratch AS payload
COPY --from=qualification-runtime /opt/quad/ /quad/

FROM qualification-runtime AS fixture
