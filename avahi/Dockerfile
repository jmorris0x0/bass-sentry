# base image
ARG ARCH=amd64
FROM $ARCH/alpine:3

# install packages
RUN apk --no-cache --no-progress add avahi avahi-tools

# remove default services
RUN rm /etc/avahi/services/*

COPY mymasterservice.service /etc/avahi/services/

# disable d-bus
RUN sed -i 's/.*enable-dbus=.*/enable-dbus=no/' /etc/avahi/avahi-daemon.conf

# entrypoint
ADD docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT [ "docker-entrypoint.sh" ]

# default command
CMD ["avahi-daemon"]
