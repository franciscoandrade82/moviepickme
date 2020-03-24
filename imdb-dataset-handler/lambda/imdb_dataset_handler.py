# -*- coding: utf-8 -*-
"""
Handles imdb datasets download
1. Get all datasets
2. Store in S3 bucket
"""

import logging
import gzip
import os
from io import BytesIO

import requests
import boto3

from boto3.s3.transfer import TransferConfig

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)


class ImdbDatasetHandler:
    """ Class to handle the download of the files """

    def __init__(self):
        self.basedir = os.getenv("BASEDIR", "/tmp/")
        self.base_url = os.getenv(
            "IMDB_DATASET_BASE_URL", "https://datasets.imdbws.com/"
        )
        # self.aws_id = os.getenv("AWS_ID")  # get this from SSM
        # self.aws_secret = os.getenv("AWS_SECRET")  # get this from SSM
        self.s3_bucket = os.getenv("STORAGE_BUCKET")
        self.datasets = os.getenv("IMDB_DATASET_FILES").split(
            ";"
        )  # this is ; separated list

    def handle(self):
        """ Process all datasets """
        s3_conn = boto3.client("s3")

        LOGGER.debug("Datasets to process '%s'", self.datasets)

        for dataset in self.datasets:
            LOGGER.debug("Processing '%s'", dataset)

            self._download(dataset)
            self._upload(dataset)
            self._uncompress(s3_conn, dataset)
            self._delete_compressed_file(s3_conn, dataset)

    def _download(self, dataset):
        """ Download imdb file dataset """

        url = self.base_url + dataset
        local_file = self.basedir + dataset

        LOGGER.debug("Download file from '%s' to '%s'", url, local_file)

        # Use a chunk size of 50 MiB (feel free to change this)
        chunk_size = 52428800

        # NOTE the stream=True parameter below
        with requests.get(url, stream=True) as request:
            request.raise_for_status()
            with open(local_file, "wb") as file:
                for chunk in request.iter_content(chunk_size=chunk_size):
                    if chunk:  # filter out keep-alive new chunks
                        file.write(chunk)

        LOGGER.debug("Finish the download, total size: %s", os.path.getsize(local_file))

    def _upload(self, dataset):
        """ Upload the downloaded dataset file to S3 """

        LOGGER.debug("Upload uncompress file to S3")

        config = TransferConfig(
            multipart_threshold=1024 * 25,
            max_concurrency=10,
            multipart_chunksize=1024 * 25,
            use_threads=True,
        )

        filename = dataset
        file_fulpath = self.basedir + filename

        LOGGER.debug(
            "Uploaded file '%s' to '%s'",
            file_fulpath,
            (self.s3_bucket + "/" + filename),
        )

        s3_conn = boto3.resource("s3")
        s3_conn.meta.client.upload_file(
            file_fulpath,
            self.s3_bucket,
            filename,
            ExtraArgs={"ACL": "public-read", "ContentType": "text/tsv"},
            Config=config,
        )

    def _uncompress(self, s3_client, dataset):
        """ Uncompress file in S3 bucket """
        uncompress_filename = dataset.replace(".gz", "")
        compressed_file = self._get_compressed_file(s3_client, dataset)

        LOGGER.debug("Uncompress file '%s' to '%s'", dataset, uncompress_filename)
        s3_client.upload_fileobj(
            Fileobj=gzip.GzipFile(None, "rb", fileobj=BytesIO(compressed_file)),
            Bucket=self.s3_bucket,
            Key=uncompress_filename,
        )

        LOGGER.debug("Finish to unzip file '%s'", uncompress_filename)

    def _get_compressed_file(self, client, dataset):
        compressed_file = client.get_object(Bucket=self.s3_bucket, Key=dataset)[
            "Body"
        ].read()

        LOGGER.debug(
            "Downloaded file '%s' from S3 with total size '%s'",
            dataset,
            len(compressed_file),
        )

        return compressed_file

    def _delete_compressed_file(self, client, dataset):
        client.delete_object(Bucket=self.s3_bucket, Key=dataset)

        LOGGER.debug("Delete uncompressed file '%s'", dataset)