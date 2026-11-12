FROM public.ecr.aws/lambda/microvms@sha256:c11ebc6785cc781bf9b6b2de43b5a9681a39141d3fdfb85a48600a6846dda2fd AS snapsafe
RUN dnf install -y openssl-snapsafe-libs \
    && mkdir /opt/snapsafe \
    && rpm -ql openssl-snapsafe-libs > /tmp/snapsafe-files \
    && for name in ssl crypto; do \
         library=$(sed -n "\|/lib${name}\.so\.3$|p" /tmp/snapsafe-files); \
         test -n "$library" && cp -L "$library" "/opt/snapsafe/lib${name}.so.3" || exit 1; \
       done \
    && rpm -q openssl-snapsafe-libs > /opt/snapsafe/packages.txt

FROM docker.io/library/debian:trixie-slim@sha256:24a01011d10eba3a023bc8585b9650b8b29021240d4217c05b905e09ef4a5232
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gstreamer1.0-plugins-bad gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-ugly gstreamer1.0-tools libcurl4t64 libgcc-s1 \
    liblog4cplus-2.0.5t64 libsrtp2-1 libssl3t64 libstdc++6 libusrsctp2 libwebsockets19t64 zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY quad/ /opt/quad/
COPY --from=snapsafe /opt/snapsafe/ /opt/snapsafe/
ENV LD_LIBRARY_PATH=/opt/snapsafe
ENV HOME=/tmp XDG_CACHE_HOME=/tmp
ENV GST_PLUGIN_SYSTEM_PATH_1_0=/opt/quad/plugins
RUN test "$(uname -m)" = aarch64 \
    && dpkg-query -W > /opt/quad/evidence/microvm-runtime-packages.txt \
    && ldd -r /opt/quad/bin/virtual-quad-media > /opt/quad/evidence/microvm-runtime-links.txt 2>&1 \
    && ! grep -E 'not found|undefined symbol' /opt/quad/evidence/microvm-runtime-links.txt \
    && grep -q '/opt/snapsafe/libssl.so.3' /opt/quad/evidence/microvm-runtime-links.txt \
    && grep -q '/opt/snapsafe/libcrypto.so.3' /opt/quad/evidence/microvm-runtime-links.txt \
    && ldd /opt/quad/bin/arducopter > /opt/quad/evidence/sitl-runtime-links.txt \
    && ! grep -q 'not found' /opt/quad/evidence/sitl-runtime-links.txt \
    && cat /opt/quad/evidence/microvm-runtime-links.txt /opt/quad/evidence/sitl-runtime-links.txt \
    && mkdir /opt/quad/plugins \
    && for plugin in coreelements videotestsrc x264 videoparsersbad app; do \
         source="/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgst$plugin.so"; \
         test -r "$source" && ln -s "$source" /opt/quad/plugins/ || exit 1; \
       done
USER 10001:10001
RUN for plugin in videotestsrc x264enc h264parse appsink appsrc; do gst-inspect-1.0 "$plugin" >/dev/null || exit 1; done
EXPOSE 8080
ENTRYPOINT ["/opt/quad/bin/virtual-quad-qualification"]
CMD ["microvm"]
