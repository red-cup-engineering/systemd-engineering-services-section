FROM ubuntu@sha256:7cc5e35f6567ee8c66d2abb4aab0fd866669e6207c237c3a8f0947a5c7f17092
ARG SOURCE_VERSION=257.9-0ubuntu2.5
ENV container=docker DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
RUN apt-get update && apt-get install --yes --no-install-recommends \
    systemd=${SOURCE_VERSION} libsystemd-shared=${SOURCE_VERSION} dbus python3 ca-certificates \
    && apt-get clean
COPY test/qualify-empty-frozen-thaw.py /opt/rce/qualify-empty-frozen-thaw.py
STOPSIGNAL SIGRTMIN+3
CMD ["/usr/lib/systemd/systemd"]
