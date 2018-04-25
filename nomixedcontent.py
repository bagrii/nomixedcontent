"""
Recursively scan web page for mixed content issues.
(c) onethinglab.com
"""

import requests
import os
import argparse

from collections import defaultdict
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed as task_completed

# number of threads to scan web pages for outgoing URL's
MAX_WORKERS = 5
# number of levels to perform scanning
MAX_CRAWL_DEPTH = 3
# what would appear in web server log files
USER_AGENT_HEADER = {'user-agent': 'NoMixedContent/v1.0 Scan web page for mixed content issues'}


def is_same_netloc(url_x, url_y):
    """returns if two URL's are on the same network location"""
    return urlparse(url_x).netloc == urlparse(url_y).netloc


def valid_content_type(content_type):
    """returns if content type is what we are looking for"""
    return "text/html" in content_type


def check_mixed_content(pages):
    """returns list of URL's with mixed content resources, if any"""
    tags_to_check = [('img', 'src'), ('iframe', 'src'), ('script', 'src'),
                     ('object', 'data'), ('form', 'action'), ('embed', 'src'),
                     ('video', 'src'), ('audio', 'src'), ('source', 'src'),
                     ('link', 'href'), ('style', '')]
    mixed_content = defaultdict(list)
    for page_url in pages:
        response = requests.get(page_url, headers=USER_AGENT_HEADER)
        if requests.codes.ok == response.status_code \
                and is_same_netloc(page_url, response.url):
            bs = BeautifulSoup(response.text, 'lxml')
            for tag_name, tag_attr in tags_to_check:
                all_tags = bs.find_all(tag_name)
                for tag in all_tags:
                    if tag_attr:
                        attr_value = tag.attrs.get(tag_attr)
                        if attr_value and 'http:' in attr_value:
                            mixed_content[page_url].append(attr_value)
                    if ('script' == tag_name or 'style' == tag_name) and \
                            'http:' in tag.text:
                        mixed_content[page_url].append(tag)

    return mixed_content


def get_all_urls(page_url):
    """returns all URL's from web page on the same network location"""
    web_page_ext = ['.htm', '.html', '.js', '.aspx', 'aspx', '.pl',
                    '.php', '.php3', '.cfm', '.cfml', '.py', '.cgi']
    all_urls = list()
    try:
        response = requests.get(page_url, headers=USER_AGENT_HEADER)
        # status OK and no redirects to another domain?
        if requests.codes.ok == response.status_code \
                and is_same_netloc(page_url, response.url) \
                and valid_content_type(response.headers['content-type']):
            # iterate over all <a> HTML element
            for tag in BeautifulSoup(response.text, 'lxml').find_all('a'):
                href_url = tag.attrs.get('href')
                if href_url == page_url or href_url == "/":
                    # skip the same page
                    continue
                phref_url = urlparse(href_url)
                _, ext = os.path.splitext(phref_url.path)
                if not (len(ext) == 0 or ext.lower() in web_page_ext):
                    # skip unknown resources
                    continue
                page_url_netloc = urlparse(page_url).netloc
                # only interested in outgoing link
                if href_url and href_url[0] != '#':
                    if "https" == phref_url.scheme \
                            and phref_url.netloc == page_url_netloc:
                        all_urls.append(href_url)
                    elif len(phref_url.scheme) == 0 and \
                                    len(phref_url.netloc) == 0 and \
                                    len(phref_url.path) > 0:
                        # this is relative URL, join with root
                        all_urls.append(urljoin(page_url, href_url))
    except Exception as e:
        print("Exception occurred while enumerating URL's for ", page_url, e)
    return all_urls


def report_mixed_content(page_url, resources):
    """pretty print mixed content resources"""
    print(">> Mixed content for {}:".format(page_url))
    for resource in resources:
        print(resource)
    print()


def scan(page_url, reporter, crawl_depth=MAX_CRAWL_DEPTH,
         max_workers=MAX_WORKERS):
    """scan web page for mixed content issues; report all found
    issues using reporter function, which receives original page url
    with a bunch of mixed content URL's."""
    crawl_urls = { page_url }
    # prevent looping around already visited pages
    visited_urls = set()

    for depth in range(crawl_depth):
        if not crawl_urls:
            # nothing to scan
            break
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            mixed_content = check_mixed_content(crawl_urls)
            for page_url, resources in mixed_content.items():
                # report found issues
                reporter(page_url, resources)
            tasks = [executor.submit(get_all_urls, url) for url in crawl_urls]
            crawl_urls.clear()
            # merge all URL's into the next batch
            for task in task_completed(tasks):
                new_urls = set(task.result())
                crawl_urls.update(new_urls - visited_urls)
                visited_urls.update(new_urls)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Recursive scan web page for mixed content issues")
    args = parser.parse_args()
    print(">> Start scanning ", args.url)
    scan(args.url, report_mixed_content)
    print(">> Done")
