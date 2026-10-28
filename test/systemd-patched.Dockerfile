ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY product /opt/rce/product
RUN apt-get install --yes --no-install-recommends \
    /opt/rce/product/systemd_257.9-0ubuntu2.5+rce.emptythaw1_amd64.deb \
    /opt/rce/product/libsystemd-shared_257.9-0ubuntu2.5+rce.emptythaw1_amd64.deb
