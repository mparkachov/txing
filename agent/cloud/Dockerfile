# The MicroVM service builds this context for ARM64. Never inject AWS keys,
# profiles, a Thing ID, a runtime identity or KVS sessions into the image.
FROM public.ecr.aws/lambda/microvms@sha256:c11ebc6785cc781bf9b6b2de43b5a9681a39141d3fdfb85a48600a6846dda2fd AS build
RUN test "$(uname -m)" = aarch64
# AL2023 starts with the minimal curl packages; explicitly replace them before
# installing the development package that requires the full libcurl provider.
RUN dnf swap -y libcurl-minimal libcurl-full \
    && dnf swap -y curl-minimal curl-full \
    && dnf install -y gcc gcc-c++ make git tar gzip unzip binutils ca-certificates \
      openssl-devel openssl-snapsafe-libs zlib-devel libcurl-devel libsrtp-devel \
    && dnf clean all
RUN curl --fail --location --silent --show-error \
      https://github.com/Kitware/CMake/releases/download/v3.31.6/cmake-3.31.6-linux-aarch64.tar.gz \
      -o /tmp/cmake.tar.gz \
    && echo 'b4cc788d63112b2749b40627e719eb5d3b8ed8f00c36d77189f4019cfe64bc9e  /tmp/cmake.tar.gz' | sha256sum --check \
    && tar -xzf /tmp/cmake.tar.gz -C /opt \
    && rm /tmp/cmake.tar.gz
ENV PATH="/opt/cmake-3.31.6-linux-aarch64/bin:${PATH}"
# Select the installed patched libraries by RPM ownership, independent of
# their package-internal directory. Both build and runtime use this directory.
RUN mkdir -p /opt/snapsafe/include \
    && rpm -ql openssl-snapsafe-libs > /opt/snapsafe/package-files.txt \
    && for name in ssl crypto; do \
         library=$(sed -n "\|/lib${name}\.so\.3$|p" /opt/snapsafe/package-files.txt); \
         test -n "$library"; \
         cp -L "$library" "/opt/snapsafe/lib${name}.so.3"; \
         ln -s "lib${name}.so.3" "/opt/snapsafe/lib${name}.so"; \
       done \
    && ln -s /usr/include/openssl /opt/snapsafe/include/openssl
ENV LD_LIBRARY_PATH="/opt/snapsafe"
WORKDIR /build/source
COPY source.tar /build/source.tar
COPY source-sha256.txt /build/source-sha256.txt
RUN tar -xf /build/source.tar -C /build/source && rm /build/source.tar
RUN sha256sum --check /build/source-sha256.txt
RUN cmake -S agent/probe -B /build/native \
    && cmake --build /build/native --parallel 4 \
    && test -r /usr/lib64/libwebsockets.so \
    && test -r /usr/lib64/libusrsctp.so \
    && test -r /usr/lib64/liblog4cplus.so \
    && pkg-config --modversion libwebsockets
COPY build-id.txt source-revision.txt source-sha256.txt /opt/txing/
RUN cmake -S agent -B /build/agent -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
      -DOPENSSL_ROOT_DIR=/opt/snapsafe \
      -DTXING_AGENT_BUILD_ID="$(cat /opt/txing/build-id.txt)" \
    && cmake --build /build/agent --parallel 4 \
    && ctest --test-dir /build/agent --output-on-failure \
    && readelf -h /build/agent/txing-agent | tee /opt/txing/elf-header.txt \
    && readelf -h /build/agent/txing-agent | grep -q AArch64 \
    && cp /build/agent/txing-agent /opt/txing/txing-agent \
    && mkdir -p /opt/txing/lib \
    && cp -L /usr/lib64/libwebsockets.so.* /usr/lib64/libusrsctp.so.* \
         /usr/lib64/liblog4cplus*.so.* /opt/txing/lib/ \
    && rpm -qa | sort > /opt/txing/packages.txt

FROM public.ecr.aws/lambda/microvms@sha256:c11ebc6785cc781bf9b6b2de43b5a9681a39141d3fdfb85a48600a6846dda2fd
RUN dnf swap -y libcurl-minimal libcurl-full \
    && dnf swap -y curl-minimal curl-full \
    && dnf install -y libstdc++ libsrtp zlib openssl-snapsafe-libs ca-certificates \
    && dnf clean all
COPY --from=build /opt/txing /opt/txing
COPY --from=build /opt/snapsafe /opt/snapsafe
COPY aws-roots.pem /opt/txing/aws-roots.pem
ENV LD_LIBRARY_PATH="/opt/snapsafe:/opt/txing/lib"
RUN ldd /opt/txing/txing-agent > /opt/txing/linked-libraries.txt \
    && ! grep -q 'not found' /opt/txing/linked-libraries.txt \
    && grep -q '/opt/snapsafe/libcrypto.so.3' /opt/txing/linked-libraries.txt \
    && grep -q '/opt/snapsafe/libssl.so.3' /opt/txing/linked-libraries.txt \
    && rpm -qa | sort > /opt/txing/runtime-packages.txt \
    && chmod -R a+rX /opt/txing /opt/snapsafe
USER 10001:10001
WORKDIR /opt/txing
EXPOSE 8080 8081
ENTRYPOINT ["/opt/txing/txing-agent", "--microvm", "--require-assignment", "--ca", "/opt/txing/aws-roots.pem"]
