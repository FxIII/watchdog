FROM python:3-alpine
MAINTAINER FxIII <fx@myself.example.com>

COPY app /app
WORKDIR /

# Add Tini
RUN apk --no-cache add  tini build-base \
    && pip install -r app/requirement.txt \
    && apk del build-base \
    && rm /root/.cache/* -rf \
    && rm -rf /var/acke/apk/*

# RUN pip install -r app/requirement.txt

EXPOSE 8080

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/startup.sh"]
