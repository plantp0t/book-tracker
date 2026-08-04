import requests
from bs4 import BeautifulSoup
from datetime import date
import boto3
from boto3.dynamodb.conditions import Key
import os

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('book_history')
tracked_table = dynamodb.Table('tracked_books')


def scrape_book(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    book_id = url.split("/")[-1]

    title_element = soup.select_one("#price-general h2")
    price_element = soup.select_one(".quantity")
    stock_element = soup.select_one("span.cart[data-quantity]")

    title = title_element.text.strip()
    price = round(float(price_element["data-price"]))
    original_price = round(float(price_element["data-originalprice"]))
    quantity = int(stock_element["data-quantity"])

    today_str = date.today().strftime("%Y-%m-%d")

    return {
        "book_id": book_id,
        "date": today_str,
        "title": title,
        "price": price,
        "original_price": original_price,
        "quantity": quantity
    }


def get_previous_record(book_id):
    response = table.query(
        KeyConditionExpression=Key('book_id').eq(book_id),
        ScanIndexForward=False,
        Limit=1
    )
    items = response['Items']
    if items:
        return items[0]
    return None


def get_active_books():
    response = tracked_table.scan()
    items = response['Items']
    return [item for item in items if item.get('active')]


def send_alert(alerts):
    topic_url = os.environ['NTFY_TOPIC_URL']
    message = "\n".join(alerts)
    requests.post(topic_url, data=message)


def send_error_alert(errors):
    topic_url = os.environ['NTFY_ERROR_TOPIC_URL']
    message = "\n".join(errors)
    requests.post(topic_url, data=message)


def lambda_handler(event, context):
    books = get_active_books()

    alerts = []
    errors = []

    for book in books:
        url = book["url"]
        try:
            result = scrape_book(url)
            previous = get_previous_record(result["book_id"])

            if previous:
                old_price = previous["price"]
                new_price = result["price"]

                if new_price < old_price:
                    percent_drop = (old_price - new_price) / old_price * 100
                    if percent_drop >= 5:
                        alerts.append(f"Price drop: {result['title']} — {old_price} → {new_price} Lekë")

                if previous["quantity"] == 0 and result["quantity"] > 0:
                    alerts.append(f"Back in stock: {result['title']}")

            table.put_item(Item=result)

        except Exception as e:
            errors.append(f"Failed to process {url}: {e}")

    if alerts:
        send_alert(alerts)

    if errors:
        send_error_alert(errors)

    return {
        'statusCode': 200,
        'body': {
            "scraped": len(books),
            "alerts": alerts,
            "errors": errors
        }
    }