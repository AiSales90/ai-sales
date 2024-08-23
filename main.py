from dotenv import load_dotenv
import streamlit as st
import pandas as pd
import requests
import os
import pickle
import logging
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from pymongo import MongoClient
from openai import OpenAI
import streamlit.components.v1 as components
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import re
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)

load_dotenv()

# Define the API key in the code
API_KEY = os.getenv("API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar"
CLIENT_SECRET_FILE = os.getenv("CLIENT_SECRET_FILE")
TOKEN_FILE = os.getenv("TOKEN_FILE")
CALENDAR_URL = os.getenv("CALENDAR_URL")
client = OpenAI(api_key=OPENAI_API_KEY)
# Initialize MongoDB client
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["call_data"]
collection = db["call_summaries"]
collectionSecond = db["userMettingDetails"]
user_details_collection = db["user_details"]
calendar_credentials_file = CLIENT_SECRET_FILE
calendar_scopes = [GOOGLE_SCOPES]
token_file = TOKEN_FILE

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# Main Streamlit app
def main():
    st.title("AI Call")
    option = st.sidebar.radio(
        "Select an option",
        [
            "Single Call",
            "Bulk Call",
            "Call Logs",
            "Show Meetings",
            "Show Name, Transcript & Summary",
            "User Details",
        ],
    )
    if option == "Single Call":
        single_call()
    elif option == "Bulk Call":
        bulk_call()
    elif option == "Call Logs":
        call_logs()
    elif option == "Show Meetings":
        show_meetings()
    elif option == "Show Name, Transcript & Summary":
        show_name_transcript_summary()
    elif option == "User Details":
        display_user_details()

# Function to make a single call
def single_call():
    st.subheader("Single Call")
    phone_number = st.text_input("Enter Phone Number")
    task = st.text_area("Enter task prompt for single call")
    transfer_phone_number = st.text_input("Enter the Transfer Phone Number")
    make_call_button = st.button("Make Call")
    if make_call_button and phone_number and task and transfer_phone_number:
        response = make_single_call_api(phone_number, task, transfer_phone_number)
        logging.debug(f"make_call_button pressed: response={response}")

# Function to make bulk calls
def bulk_call():
    st.subheader("Bulk Call")
    uploaded_file = st.file_uploader("Upload CSV File", type=["csv"])
    task = st.text_area("Enter task prompt for bulk calls")
    transfer_phone_number = st.text_input("Enter the Transfer Phone Number")
    make_bulk_call_button = st.button("Make Bulk Call")
    if (
        make_bulk_call_button
        and uploaded_file is not None
        and task
        and transfer_phone_number
    ):
        response = make_bulk_call_api(uploaded_file, task, transfer_phone_number)
        logging.debug(f"make_bulk_call_button pressed: response={response}")

# Function to fetch call logs
def call_logs():
    st.subheader("Call Logs")
    response = fetch_call_logs_api()
    logging.debug(f"fetch_call_logs_api response: {response}")

    if response and "calls" in response:
        calls = response["calls"]
        if calls:
            df = pd.DataFrame(calls)
            logging.debug(f"Calls DataFrame: {df}")

            desired_columns = [
                "created_at",
                "to",
                "from",
                "call_length",
                "price",
                "status",
                "call_id",
            ]

            existing_columns = [col for col in desired_columns if col in df.columns]
            if existing_columns:
                df = df[existing_columns]
                st.write(df)

                for index, row in df.iterrows():
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button(
                            f"View Transcript for {row['call_id']}",
                            key=f"transcript_{row['call_id']}",
                        ):
                            st.session_state["call_id"] = row["call_id"]
                            show_transcript_and_summary(row["call_id"])
                            logging.debug(
                                f"Transcript button pressed for call_id={row['call_id']}"
                            )
                    with col2:
                        if st.button(
                            f"View Summary for {row['call_id']}",
                            key=f"summary_{row['call_id']}",
                        ):
                            st.session_state["call_id"] = row["call_id"]
                            show_transcript_and_summary(row["call_id"])
                            logging.debug(
                                f"Summary button pressed for call_id={row['call_id']}"
                            )
            else:
                st.warning("No recognizable columns found in the call data.")
                logging.warning("No recognizable columns found in the call data.")
        else:
            st.info("No calls found in the response.")
            logging.info("No calls found in the response.")
    else:
        st.error("Failed to fetch call logs or received an invalid response.")
        logging.error("Failed to fetch call logs or received an invalid response.")

def show_transcript_and_summary(call_id):
    url = f"https://api.bland.ai/v1/calls/{call_id}"
    headers = {"Authorization": API_KEY}
    response = requests.get(url, headers=headers)
    logging.debug(
        f"Fetching transcript and summary for call_id={call_id}: response={response}"
    )

    if response.status_code == 200:
        call_details = response.json()
        logging.debug(f"call_details: {call_details}")
        concatenated_transcript = call_details.get("concatenated_transcript", "")
        summary = call_details.get("summary", "No summary available.")
        st.text_area("Transcript", concatenated_transcript, height=300)
        st.text_area("Summary", summary, height=300)

        store_transcript_and_summary(call_id, concatenated_transcript, summary)

        # Fetch name and email from the call details or use placeholder values
        name = call_details.get("name", "Unknown")
        email = call_details.get("email", "unknown@example.com")

        user_details = extract_user_details(concatenated_transcript, name, email)
        logging.debug(f"Extracted user_details: {user_details}")

        if user_details:
            name = user_details.get("Name", "")
            date = user_details.get("Date", "")
            time = user_details.get("Time", "")
            email = user_details.get("Email", "")
            if name and date and time and email:
                meeting_link = create_event(name, date, time, email)
                logging.debug(f"Created meeting link: {meeting_link}")
                if meeting_link:
                    st.success(f"Meeting scheduled successfully! Meeting link: {meeting_link}")
                    store_user_details_with_meeting_link(user_details, meeting_link)
                    email_response = send_email_with_smtp(name, email, meeting_link)
                    if email_response:
                        st.success("Email sent successfully!")
                else:
                    st.error("Failed to send email after multiple attempts. Please check the logs for details.")
            else:
                st.error("Failed to create meeting.")
        else:
            st.error("Invalid details extracted, cannot create event.")
            logging.error("Invalid details extracted, cannot create event.")
    else:
        st.error("Failed to extract user details.")
        logging.error("Failed to extract user details.")
# else:
#     st.error("Failed to fetch transcript and summary.")
#     logging.error("Failed to fetch transcript and summary.")

# Function to make a single call using API
def make_single_call_api(phone_number, task, transfer_phone_number):
    headers = {"Authorization": API_KEY}
    data = {
        "phone_number": phone_number,
        "task": task,
        "language": "en",
        "voice": "e1289219-0ea2-4f22-a994-c542c2a48a0f",
        "transfer_phone_number": transfer_phone_number,
    }
    response = requests.post(
        "https://api.bland.ai/v1/calls", data=data, headers=headers
    )
    logging.debug(f"make_single_call_api response: {response.json()}")
    st.write(response.json())
    return response

def make_bulk_call_api(uploaded_file, task, transfer_phone_number):
    headers = {"Authorization": API_KEY}
    try:
        df = pd.read_csv(uploaded_file, skipinitialspace=True)
        df.columns = df.columns.str.strip()
        logging.debug(f"Bulk call uploaded CSV DataFrame: {df}")
        if "name" in df.columns and "phone_number" in df.columns and "email" in df.columns:
            for index, row in df.iterrows():
                name = row["name"].strip()
                phone_number = "+" + str(row["phone_number"]).strip().lstrip("+")
                email = row["email"].strip()
                task_prompt = task.format(name=name)
                data = {
                    "phone_number": phone_number,
                    "task": task_prompt,
                    "language": "en",
                    "transfer_phone_number": transfer_phone_number,
                }
                response = requests.post("https://api.bland.ai/v1/calls", data=data, headers=headers)
                logging.debug(f"Bulk Call Response for {phone_number}: {response.json()}")
                st.write(response.json())
                if response.status_code == 200:
                    call_details = response.json()
                    call_details["email"] = email
                    call_details["name"] = name
                    process_call_completion(call_details)
            return response
        else:
            st.error("Columns 'name', 'phone_number', or 'email' not found in the uploaded file.")
            logging.error("Columns 'name', 'phone_number', or 'email' not found in the uploaded file.")
    except Exception as e:
        st.error(f"Error: {e}")
        logging.error(f"make_bulk_call_api Error: {e}")

# Function to fetch call logs using API
def fetch_call_logs_api():
    url = "https://api.bland.ai/v1/calls"
    headers = {"Authorization": API_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"fetch_call_logs_api data: {data}")
        return data
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch call logs. Error: {e}")
        logging.error(f"fetch_call_logs_api Error: {e}")
        return None

def extract_user_details(summary, name, email):
    logging.info(f"Extracting user details from summary: {summary[:100]}...")  # Log first 100 chars of summary
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an AI assistant tasked with extracting the interview date and time from a call transcript. Respond ONLY with the date in YYYY/MM/DD format and the time in 24-hour HH:MM format, separated by a comma. If you can't find an exact date or time, use your best judgment to infer it from the context. If you absolutely can't determine a date or time, respond with 'Unable to determine'."},
                {"role": "user", "content": f"Extract the interview date and time from this transcript: {summary}"}
            ],
            temperature=0.3,
            max_tokens=50,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        details = response.choices[0].message.content.strip()
        logging.debug(f"OpenAI extract_user_details raw response: {details}")
        
        if "Unable to determine" in details:
            logging.warning("AI unable to determine date and time")
            return None

        # Parse the response
        match = re.match(r'(\d{4}/\d{2}/\d{2}),\s*(\d{2}:\d{2})', details)
        if match:
            date, time = match.groups()
            details_dict = {'Date': date, 'Time': time, 'Name': name, 'Email': email}
            
            # Validate date and time format
            try:
                parsed_datetime = datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M")
                # Ensure the date is in the future
                if parsed_datetime <= datetime.now():
                    parsed_datetime += timedelta(days=1)
                details_dict['Date'] = parsed_datetime.strftime("%Y/%m/%d")
                details_dict['Time'] = parsed_datetime.strftime("%H:%M")
            except ValueError as e:
                logging.error(f"Invalid date or time format: {e}")
                return None

            logging.info(f"Successfully parsed user details: {details_dict}")
            return details_dict
        else:
            logging.error(f"Failed to parse AI response: {details}")
            return None
    except Exception as e:
        logging.error(f"Error extracting details from OpenAI: {e}")
        return None

def show_transcript_and_summary(call_id):
    url = f"https://api.bland.ai/v1/calls/{call_id}"
    headers = {"Authorization": API_KEY}
    response = requests.get(url, headers=headers)
    logging.debug(
        f"Fetching transcript and summary for call_id={call_id}: response={response}"
    )

    if response.status_code == 200:
        call_details = response.json()
        logging.debug(f"call_details: {call_details}")
        concatenated_transcript = call_details.get("concatenated_transcript", "")
        summary = call_details.get("summary", "No summary available.")
        st.text_area("Transcript", concatenated_transcript, height=300)
        st.text_area("Summary", summary, height=300)

        store_transcript_and_summary(call_id, concatenated_transcript, summary)

        # Fetch name and email from the call details or use placeholder values
        name = call_details.get("name", "Unknown")
        email = call_details.get("email", "unknown@example.com")

        user_details = extract_user_details(concatenated_transcript, name, email)
        logging.debug(f"Extracted user_details: {user_details}")

        if user_details:
            name = user_details.get("Name", "")
            date = user_details.get("Date", "")
            time = user_details.get("Time", "")
            email = user_details.get("Email", "")
            if name and date and time and email:
                meeting_link = create_event(name, date, time, email)
                logging.debug(f"Created meeting link: {meeting_link}")
                if meeting_link:
                    st.success(
                        f"Meeting scheduled successfully! Meeting link: {meeting_link}"
                    )
                    store_user_details_with_meeting_link(user_details, meeting_link)
                    email_response = send_email_with_smtp(name, email, meeting_link)
                    logging.debug(f"Email sent response: {email_response}")
                    if email_response:
                        st.success("Email sent successfully!")
                    else:
                        st.error("Failed to send email.")
                else:
                    st.error("Failed to create meeting.")
            else:
                st.error("Invalid details extracted, cannot create event.")
                logging.error("Invalid details extracted, cannot create event.")
        else:
            st.error("Failed to extract user details.")

# Function to store details in MongoDB
def store_in_mongodb(details):
    try:
        if isinstance(details, dict):
            existing_meeting = collectionSecond.find_one(
                {
                    "Name": details["Name"],
                    "Email": details["Email"],
                    "Date": details["Date"],
                    "Time": details["Time"],
                }
            )
            if not existing_meeting:
                collectionSecond.insert_one(details)
                logging.debug("Stored user meeting details in MongoDB")
            else:
                logging.info(
                    "User meeting details with the same Name, Email, Date, and Time already exist in MongoDB"
                )
        else:
            st.error("Failed to store details: details are not in the correct format.")
            logging.error(
                "Failed to store details: details are not in the correct format."
            )
    except Exception as e:
        st.error(f"Error storing details in MongoDB: {e}")
        logging.error(f"store_in_mongodb Error: {e}")

# Function to store transcript and summary in MongoDB
# Function to store transcript and summary in MongoDB
def store_transcript_and_summary(call_id, transcript, summary):
    try:
        existing_call = collection.find_one({"call_sid": call_id})
        if not existing_call:
            collection.update_one(
                {"call_sid": call_id},
                {
                    "$set": {
                        "transcript_and_summary": {
                            "transcript": transcript,
                            "summary": summary,
                        }
                    }
                },
                upsert=True,
            )
            logging.debug("Stored transcript and summary in MongoDB")
        else:
            logging.info(
                f"Call details with call_id={call_id} already exist in MongoDB"
            )
    except Exception as e:
        st.error(f"Error storing transcript and summary in MongoDB: {e}")
        logging.error(f"store_transcript_and_summary Error: {e}")

# Function to get Google Calendar service
def get_calendar_service():
    creds = None
    try:
        if os.path.exists(token_file):
            with open(token_file, "rb") as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    calendar_credentials_file, calendar_scopes
                )
                flow.redirect_uri = "https://ai-sales-7g8n.onrender.com"
                creds = flow.run_local_server(port=0)
                with open(token_file, "wb") as token:
                    pickle.dump(creds, token)
        logging.debug("Google Calendar service created")
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Error getting Google Calendar service: {e}")
        logging.error(f"get_calendar_service Error: {e}")


def create_event(name, date, time, email):
    logging.info(f"Creating event for name={name}, date={date}, time={time}, email={email}")
    try:
        # Ensure the year is current or future
        current_year = datetime.now().year
        date_parts = date.split('/')
        if int(date_parts[0]) < current_year:
            date_parts[0] = str(current_year)
            date = '/'.join(date_parts)
        logging.debug(f"Adjusted date: {date}")

        # Ensure time is correctly formatted
        if len(time) == 4:
            time = f"{time[:2]}:{time[2:]}"
        logging.debug(f"Adjusted time: {time}")

        start_datetime = f'{date.replace("/", "-")}T{time}:00'
        end_datetime = (datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M:%S") + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        logging.debug(f"Start datetime: {start_datetime}, End datetime: {end_datetime}")

        event = {
            'summary': f'Interview with {name}',
            'start': {
                'dateTime': start_datetime,
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': 'Asia/Kolkata',
            },
            'attendees': [
                {'email': email},
            ],
        }
        logging.debug(f"Event details: {event}")

        service = get_calendar_service()
        event = service.events().insert(calendarId='primary', body=event).execute()
        logging.info(f"Event created: {event.get('htmlLink')}")
        meeting_link = event.get('htmlLink')
        return meeting_link
    except ValueError as e:
        logging.error(f"An error occurred with date/time formatting: {e}")
        return None
    except Exception as e:
        logging.error(f"create_event Error: {e}")
        return None


def process_call_completion(call_details):
    logging.info(f"Starting process_call_completion with call_details: {call_details}")
    try:
        call_id = call_details.get('id')
        email = call_details.get('email')
        name = call_details.get('name', 'Interviewee')
        
        logging.info(f"Processing call completion for call_id={call_id}, email={email}, name={name}")
        
        # Fetch transcript and summary
        url = f"https://api.bland.ai/v1/calls/{call_id}"
        headers = {"Authorization": API_KEY}
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            call_data = response.json()
            transcript = call_data.get("concatenated_transcript", "")
            summary = call_data.get("summary", "No summary available.")
            
            logging.debug(f"Fetched transcript: {transcript[:100]}...")  # Log first 100 chars of transcript
            
            # Store transcript and summary
            store_transcript_and_summary(call_id, transcript, summary)
            
            # Extract date and time
            user_details = extract_user_details(transcript, name, email)
            logging.info(f"Extracted user_details: {user_details}")
            
            if user_details and 'Date' in user_details and 'Time' in user_details:
                date = user_details['Date']
                time = user_details['Time']
                
                logging.info(f"Extracted date: {date}, time: {time}")
                
                # Create event and get meeting link
                meeting_link = create_event(name, date, time, email)
                
                if meeting_link:
                    logging.info(f"Successfully created meeting with link: {meeting_link}")
                    # Store user details with meeting link
                    store_user_details_with_meeting_link(user_details, meeting_link)
                    
                    # Send email
                    email_sent = send_email_with_smtp(name, email, meeting_link)
                    if email_sent:
                        logging.info(f"Email sent successfully to {email}")
                    else:
                        logging.error(f"Failed to send email to {email}")
                    
                    logging.info(f"Call completion process successful for call_id={call_id}")
                else:
                    logging.error(f"Failed to create meeting for call_id={call_id}")
            else:
                logging.error(f"Failed to extract valid date and time from transcript for call_id={call_id}")
                # Implement a fallback method here, such as scheduling for the next available time slot
                fallback_date = (datetime.now() + timedelta(days=1)).strftime("%Y/%m/%d")
                fallback_time = "10:00"
                logging.info(f"Using fallback date: {fallback_date} and time: {fallback_time}")
                meeting_link = create_event(name, fallback_date, fallback_time, email)
                if meeting_link:
                    user_details = {'Name': name, 'Email': email, 'Date': fallback_date, 'Time': fallback_time}
                    store_user_details_with_meeting_link(user_details, meeting_link)
                    send_email_with_smtp(name, email, meeting_link)
                    logging.info(f"Fallback meeting scheduled for call_id={call_id}")
                else:
                    logging.error(f"Failed to schedule fallback meeting for call_id={call_id}")
        else:
            logging.error(f"Failed to fetch call details for call_id={call_id}. Status code: {response.status_code}")
    except Exception as e:
        logging.error(f"Error in process_call_completion: {e}")


def send_email_with_smtp(name, email, meeting_link, max_retries=3):
    logging.info(f"Sending email to name={name}, email={email}, meeting_link={meeting_link}")
    
    logging.debug(f"SMTP settings: Server={SMTP_SERVER}, Port={SMTP_PORT}, Username={SMTP_USERNAME}")
    
    for attempt in range(max_retries):
        try:
            msg = MIMEMultipart()
            msg['From'] = SMTP_USERNAME
            msg['To'] = email
            msg['Subject'] = 'Interview Scheduled'
            
            cc_recipients = ['sachinparmar98134@gmail.com', 'batoivan@hotmail.com', 'ivanvonberlin@googlemail.com']
            msg['Cc'] = ', '.join(cc_recipients)

            html = f'''
            <html>
              <body>
                <p>Dear {name},</p>
                <p>Your interview has been scheduled. Please find the details below:</p>
                <p><a href="{meeting_link}">Join Meeting</a></p>
                <p>Thank you.</p>
              </body>
            </html>
            '''
            msg.attach(MIMEText(html, 'html'))

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
                server.set_debuglevel(1)  # Enable debug output
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
            
            logging.info(f"Email sent successfully to {email} and CC to {', '.join(cc_recipients)}")
            return True
        except (smtplib.SMTPException, TimeoutError, ConnectionError) as e:
            logging.error(f"Attempt {attempt + 1} failed. Error sending email with SMTP: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logging.error(f"All {max_retries} attempts to send email failed.")
                return False

    return False

def show_meetings():
    st.subheader("Scheduled Meetings")
    calendar_url = CALENDAR_URL
    components.iframe(calendar_url, width=800, height=600, scrolling=True)

def show_name_transcript_summary():
    st.subheader("Name, Transcript & Summary")

    data = list(collection.find({}, {"call_sid": 1, "transcript_and_summary": 1}))

    if not data:
        st.info("No data available.")
        logging.info("No data available.")
        return

    df = pd.DataFrame(data)
    df["index"] = range(1, len(df) + 1)
    df = df.rename(columns={"call_sid": "SID"})

    st.table(df[["index", "SID"]])

    for index, row in df.iterrows():
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                f"Show Transcript {row['index']}", key=f"transcript_{row['SID']}"
            ):
                show_popup("Transcript", row["transcript_and_summary"]["transcript"])
                logging.debug(f"Show Transcript button pressed for SID={row['SID']}")
        with col2:
            if st.button(f"Show Summary {row['index']}", key=f"summary_{row['SID']}"):
                show_popup("Summary", row["transcript_and_summary"]["summary"])
                logging.debug(f"Show Summary button pressed for SID={row['SID']}")

def show_popup(title, content):
    st.subheader(title)
    st.text_area("", value=content, height=300)

def store_user_details_with_meeting_link(user_details, meeting_link):
    logging.info(f"Storing user details with meeting link: user_details={user_details}, meeting_link={meeting_link}")
    try:
        user_details['Meeting Link'] = meeting_link
        if isinstance(user_details, dict):
            existing_user = user_details_collection.find_one({
                'Name': user_details['Name'],
                'Email': user_details['Email'],
                'Date': user_details['Date'],
                'Time': user_details['Time']
            })
            if not existing_user:
                user_details_collection.insert_one(user_details)
                logging.info("Stored user details with meeting link in MongoDB")
            else:
                logging.info("User details with the same Name, Email, Date, and Time already exist in MongoDB")
        else:
            logging.error("Failed to store details: details are not in the correct format.")
    except Exception as e:
        logging.error(f"Error storing user details with meeting link in MongoDB: {e}")

def display_user_details():
    st.subheader("User Details")

    data = list(user_details_collection.find({}, {"_id": 0}))

    if not data:
        st.info("No user details available.")
        logging.info("No user details available.")
        return

    df = pd.DataFrame(data)
    df["index"] = range(1, len(df) + 1)

    df = df.rename(
        columns={
            "Name": "Name",
            "Email": "Email",
            "Date": "Date",
            "Time": "Time",
            "Meeting Link": "Meeting Link",
        }
    )

    st.table(df[["index", "Name", "Email", "Date", "Time", "Meeting Link"]])

if __name__ == "__main__":
    main()
