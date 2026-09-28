# Build context is the repository root. Publication/versioning is supplied by #158.
FROM docker.io/library/alpine:3.24.1 AS build
RUN apk add --no-cache build-base cmake ninja pkgconf git go \
    ca-certificates curl curl-dev openssl-dev log4cplus-dev libsrtp-dev \
    libusrsctp-dev libwebsockets-dev zlib-dev
WORKDIR /src
COPY devices/common/kvs devices/common/kvs
COPY devices/tbot/cloud/viewer devices/tbot/cloud/viewer
RUN cmake -S devices/tbot/cloud/viewer -B /build/viewer -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/install \
    && cmake --build /build/viewer --parallel 4 \
    && ctest --test-dir /build/viewer --output-on-failure \
    && cmake --install /build/viewer
COPY devices/tbot/cloud/go.mod devices/tbot/cloud/go.sum devices/tbot/cloud/
WORKDIR /src/devices/tbot/cloud
RUN go mod download
COPY devices/tbot/cloud/agentstatus agentstatus
COPY devices/tbot/cloud/controller controller
COPY devices/tbot/cloud/companion companion
COPY devices/tbot/cloud/cmd/txing-tbot-companion cmd/txing-tbot-companion
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -o /install/bin/txing-tbot-companion ./cmd/txing-tbot-companion

FROM docker.io/library/alpine:3.24.1
RUN apk add --no-cache ca-certificates openssl libwebsockets libsrtp libusrsctp \
      libstdc++ libgcc zlib \
    && addgroup -g 10001 agent && adduser -D -u 10001 -G agent agent \
    && cp /etc/ssl/certs/ca-cert-Starfield_Services_Root_Certificate_Authority_-_G2.pem \
      /etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem \
    && test -r /etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem
COPY --from=build /install/bin/ /usr/local/bin/
USER 10001:10001
WORKDIR /tmp
EXPOSE 14550/udp
ENTRYPOINT ["/usr/local/bin/txing-tbot-companion"]
