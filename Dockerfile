FROM python:3.6-alpine

WORKDIR /app

ENV BUILD_LIST git

RUN apk add --update $BUILD_LIST \
    && apk add gcc python-dev musl-dev \
    && git clone https://github.com/scraplesh/blockchain.git /app \
    && pip install pipenv \
    && pipenv --python=python3.6 \
    && pipenv install \
    && apk del $BUILD_LIST \
    && rm -rf /var/cache/apk/*

EXPOSE 8080

ENTRYPOINT ["pipenv", "run", "python", "/app/blockchain.py"]
