ARG BUILD_FROM
FROM ${BUILD_FROM}

# Only the Python standard library is used – no third-party packages.
RUN apk add --no-cache python3

COPY app /opt/bifrost
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/bifrost
CMD [ "/run.sh" ]
