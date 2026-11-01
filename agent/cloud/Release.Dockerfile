# Immutable prebuilt application and libraries. AWS never recompiles a release.
FROM public.ecr.aws/lambda/microvms@sha256:c11ebc6785cc781bf9b6b2de43b5a9681a39141d3fdfb85a48600a6846dda2fd
COPY runtime/txing/ /opt/txing/
COPY runtime/snapsafe/ /opt/snapsafe/
ENV LD_LIBRARY_PATH="/opt/snapsafe:/opt/txing/lib"
RUN test "$(uname -m)" = aarch64 \
    && ldd /opt/txing/txing-agent > /opt/txing/release-links.txt \
    && ! grep -q 'not found' /opt/txing/release-links.txt \
    && grep -q '/opt/snapsafe/libcrypto.so.3' /opt/txing/release-links.txt \
    && grep -q '/opt/snapsafe/libssl.so.3' /opt/txing/release-links.txt \
    && /opt/txing/txing-agent --help > /opt/txing/release-smoke.txt
USER 10001:10001
WORKDIR /opt/txing
EXPOSE 8080 8081
ENTRYPOINT ["/opt/txing/txing-agent", "--microvm", "--require-assignment", "--ca", "/opt/txing/aws-roots.pem"]
