FROM docker.io/library/golang:1.25-bookworm@sha256:83fb73a52c2b487af429f55789e3610142c8e8055abe0c2285b77f1541bcf519 AS go-build
WORKDIR /src
COPY devices/virtual-quad/runtime/supervisor/ ./
RUN CGO_ENABLED=0 go test -mod=readonly ./... \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/virtual-quad-supervisor .

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
RUN mkdir /out \
    && tar --exclude=.git -czf /out/arducopter-source.tar.gz -C / ardupilot \
    && ./waf configure --board sitl && ./waf copter -j "${BUILD_JOBS}" \
    && strip -o /out/arducopter build/sitl/bin/arducopter \
    && { git rev-parse HEAD && git submodule status --recursive; } > /out/arducopter-source.txt \
    && dpkg-query -W > /out/build-packages.txt

WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends libjson-c-dev \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg-query -W > /out/build-packages.txt
COPY devices/common/board/kvs_master devices/common/board/kvs_master
COPY devices/common/board/mavlink/include devices/common/board/mavlink/include
COPY devices/common/kvs devices/common/kvs
COPY devices/virtual-quad/runtime/CMakeLists.txt devices/virtual-quad/runtime/*.cpp devices/virtual-quad/runtime/*.hpp devices/virtual-quad/runtime/
RUN cmake -S devices/virtual-quad/runtime -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DTXING_KVS_REAL_SDK=ON \
    && CMAKE_BUILD_PARALLEL_LEVEL="${BUILD_JOBS}" cmake --build /build --target virtual-quad-media virtual-quad-camera-test virtual-quad-flight-test \
    && /build/virtual-quad-camera-test \
    && /build/virtual-quad-flight-test \
    && strip -o /out/virtual-quad-media /build/virtual-quad-media

RUN sdk=/build/kvs-master/aws-kvs-webrtc-sdk/src \
    && mkdir /out/kvs-sdk \
    && cp "$sdk/LICENSE" /out/kvs-sdk/ \
    && find "$sdk" -maxdepth 1 -type f -iname 'notice*' -exec cp {} /out/kvs-sdk/ \;

RUN printf '#include <srtp2/srtp.h>\nint main(void) { return srtp_init() != srtp_err_status_ok; }\n' > /tmp/srtp-test.c \
    && cc -o /out/srtp-test /tmp/srtp-test.c -lsrtp2

FROM scratch AS payload
COPY --from=go-build /out/virtual-quad-supervisor /quad/bin/
COPY --from=native-build /out/arducopter /out/virtual-quad-media /quad/bin/
COPY --from=native-build /out/arducopter-source.txt /out/build-packages.txt /ardupilot/COPYING.txt /quad/evidence/
COPY --from=native-build /out/kvs-sdk/ /quad/evidence/kvs-sdk/
COPY --from=native-build /out/arducopter-source.tar.gz /
COPY devices/common/kvs/sdk.commit /quad/evidence/kvs-sdk.commit
COPY devices/virtual-quad/runtime/arducopter.parm /quad/

FROM docker.io/library/debian:trixie-slim@sha256:24a01011d10eba3a023bc8585b9650b8b29021240d4217c05b905e09ef4a5232 AS lambda-runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gstreamer1.0-plugins-bad gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-ugly libcurl4t64 libgcc-s1 libjson-c5 \
    liblog4cplus-2.0.5t64 libsrtp2-1 libssl3t64 libstdc++6 libusrsctp2 \
    libwebsockets19t64 patchelf zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY --from=payload /quad/ /stage/quad/
COPY --from=native-build /out/srtp-test /stage/srtp-test
RUN set -eu \
    && mkdir -p /stage/quad/lib /stage/quad/plugins /stage/quad/certs \
    && cp -L /lib/ld-linux-aarch64.so.1 /stage/quad/lib/ld-linux-aarch64.so.1 \
    && cp -L /etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem /stage/quad/certs/starfield.pem \
    && for module in libsoftokn3.so libfreebl3.so libfreeblpriv3.so; do \
         cp -L "/usr/lib/aarch64-linux-gnu/$module" /stage/quad/lib/; \
       done \
    && for plugin in coreelements x264 videoparsersbad app; do \
         cp -L "/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgst${plugin}.so" /stage/quad/plugins/; \
       done \
    && for binary in /stage/quad/bin/arducopter /stage/quad/bin/virtual-quad-media /stage/quad/plugins/*.so \
         /stage/quad/lib/libsoftokn3.so /stage/quad/lib/libfreebl3.so /stage/quad/lib/libfreeblpriv3.so; do \
         ldd "$binary" > /tmp/quad-ldd \
         && ! grep -q 'not found' /tmp/quad-ldd \
         && awk '$2 == "=>" && $3 ~ /^\// { print $3 }' /tmp/quad-ldd | while read -r library; do \
              cp -L "$library" "/stage/quad/lib/$(basename "$library")"; \
            done; \
       done \
    && for binary in /stage/quad/bin/arducopter /stage/quad/bin/virtual-quad-media; do \
         patchelf --set-interpreter /var/task/quad/lib/ld-linux-aarch64.so.1 "$binary"; \
       done \
    && patchelf --set-interpreter /var/task/quad/lib/ld-linux-aarch64.so.1 /stage/srtp-test \
    && dpkg-query -W > /stage/quad/evidence/lambda-runtime-packages.txt

FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal@sha256:158a9044f9dc0777f098b76c8b54346f6ed4560b9a6a416dec7a5ba3bc483af4 AS lambda-verify
COPY --from=lambda-runtime /stage/quad/ /var/task/quad/
COPY --from=lambda-runtime /stage/srtp-test /tmp/srtp-test
RUN LD_LIBRARY_PATH=/var/task/quad/lib /tmp/srtp-test

FROM scratch AS lambda-payload
COPY --from=lambda-verify /var/task/quad/ /quad/
