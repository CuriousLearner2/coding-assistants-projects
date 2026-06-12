import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
import os
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SENDER_EMAIL = "gautambiswas2004@icloud.com"
RECEIVER_EMAIL = "gautambiswas2004@icloud.com"
EMAIL_PASSWORD = "jjho-mufs-iyya-nbit"
SMTP_SERVER = "smtp.mail.me.com"
SMTP_PORT = 587
LAST_ARTICLE_FILE = "last_article.txt"

def get_latest_news():
    url = "https://bangla.thedailystar.net/news/bangladesh"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None, f"HTTP Error {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all(['h3', 'h5'], class_='card-title')
        
        if not articles:
            # Fallback
            articles = soup.find_all('h5', class_='field-content')
            
        if not articles:
            return None, None, "Could not find any article tags on page"

        # Load last sent article link to avoid duplicates
        last_link = ""
        if os.path.exists(LAST_ARTICLE_FILE):
            with open(LAST_ARTICLE_FILE, 'r') as f:
                last_link = f.read().strip()

        selected_article = None
        for art in articles:
            link_tag = art.find('a')
            if link_tag and link_tag.get('href'):
                link = link_tag['href']
                if link != last_link:
                    selected_article = art
                    break
        
        # If all top articles were already sent (unlikely but possible), just take the first one
        if not selected_article:
            selected_article = articles[0]

        link_tag = selected_article.find('a')
        title = link_tag.text.strip()
        link = link_tag['href']
        
        # Store this as the last sent link
        with open(LAST_ARTICLE_FILE, 'w') as f:
            f.write(link)

        if not link.startswith('http'): 
            link = "https://bangla.thedailystar.net" + link
        
        art_response = requests.get(link, headers=headers, timeout=10)
        art_soup = BeautifulSoup(art_response.text, 'html.parser')
        paragraphs = art_soup.find_all('p')
        content = " ".join([p.text.strip() for p in paragraphs if len(p.text.strip()) > 20])
        
        if not content:
            return title, "Content could not be extracted from the article link.", None
            
        return title, content[:3000], None
    except Exception as e:
        return None, None, str(e)

def simplify_with_gemini(title, content):
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not found in environment.")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Title: {title}
    Content: {content}
    
    Simplify this Bangla news for a 7th grader. 
    Use simple words and short sentences. 
    Format:
    Subject: [Title]
    Body: [Content]
    """
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Gemini error: {e}")
        return None

def send_email(subject, body, is_failure=False):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    
    prefix = "[Daily News - Failure]" if is_failure else "[Daily News - Simplified]"
    msg['Subject'] = f"{prefix} {subject}"
    
    if body is None:
        body = "No content available."
        
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email error: {e}")

if __name__ == "__main__":
    print("Fetching news...")
    title, content, error = get_latest_news()
    
    if error:
        print(f"Scraping failure: {error}")
        send_email("Script could not reach the news site", f"Error Details: {error}", is_failure=True)
    elif title and content:
        print(f"Article found: {title}")
        ai_output = simplify_with_gemini(title, content)
        
        if ai_output:
            sub = title
            bod = ai_output
            if "Subject:" in ai_output and "Body:" in ai_output:
                try:
                    sub = ai_output.split("Subject:")[1].split("Body:")[0].strip()
                    bod = ai_output.split("Body:")[1].strip()
                except: pass
            send_email(sub, bod)
        else:
            send_email(title, f"(Note: AI simplification failed. Sending raw snippet.)\n\n{content[:1000]}...")
