"""X（Twitter）画像付き投稿モジュール（GitHub Actions 用）"""
import os
import logging

import tweepy


def _get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def _get_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return tweepy.API(auth)


def post_tweet_with_image(text: str, image_path: str) -> bool:
    """画像付き1ツイート。成功 True、重複 False。"""
    api_v1 = _get_api_v1()
    client = _get_client()
    try:
        media = api_v1.media_upload(filename=image_path)
        response = client.create_tweet(text=text, media_ids=[media.media_id])
        logging.info(f"投稿完了 tweet_id={response.data['id']}")
        return True
    except tweepy.errors.Forbidden as e:
        if "duplicate" in str(e).lower():
            logging.warning("重複スキップ")
            return False
        raise
