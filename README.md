# Recommender
This repository contains a simple content recommendation system.

It uses Google App Engine Python for the server and AngularJS for the web UI.

## Setup

1.  Install Google App Engine SDK for Python
2.  Install dependencies:
    `pip install -r requirements.txt -t lib`

3.  Compile proto definitions:


    sudo apt install protobuf-compiler
    protoc protos/*.proto --python_out=.

## Run locally
`/usr/bin/dev_appserver.py --host localhost --port 8081 .`

The server will be up at: http://localhost:8081


## Run tests
`python test_runner.py /usr/lib/google-cloud-sdk`

## Deploy
To deploy on App Engine:

    export $PROJECT_ID=<insert your project id here> 
    gcloud app create --project $PROJECT_ID
    gcloud datastore indexes create --quiet --project $PROJECT_ID index.yaml
    gcloud app deploy --quiet --project $PROJECT_ID queue.yaml
    gcloud app deploy --quiet --project $PROJECT_ID .

## License

Apache License 2.0.

This is not an officially supported Google product.
