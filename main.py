from dotenv import load_dotenv
import streamlit as st
import pandas as pd
import requests
import os
import pickle
import logging
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from pymongo import MongoClient
from openai import OpenAI
import streamlit.components.v1 as components
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Configure logging
logging.basicConfig(level=logging.DEBUG)

load_dotenv()

# Define the API key in the code
API_KEY = os.getenv("API_KEY")
MONGO_URI = os.getenv('MONGO_URI')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
# Initialize OpenAI API key
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar"
CLIENT_SECRET_FILE = os.getenv('CLIENT_SECRET_FILE')
TOKEN_FILE = os.getenv('TOKEN_FILE')
CALENDAR_URL = os.getenv("CALENDAR_URL")
client = OpenAI(api_key=OPENAI_API_KEY)
# Initialize MongoDB client
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["call_data"]
collection = db["call_summaries"]
collectionSecond = db["userMettingDetails"]
user_details_collection = db["user_details"]  # New collection for user details and meeting link
calendar_credentials_file = CLIENT_SECRET_FILE  # Update with client's credentials file
calendar_scopes = [GOOGLE_SCOPES]
token_file = TOKEN_FILE  # Ensure this token file is used for client's credentials

# Main Streamlit app
def main():
    st.title("AI Call")
    
    option = st.sidebar.radio("Select an option", ["Single Call", "Bulk Call", "Call Logs", "Show Meetings", "Show Name, Transcript & Summary", "User Details"])

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
    if make_bulk_call_button and uploaded_file is not None and task and transfer_phone_number:
        response = make_bulk_call_api(uploaded_file, task, transfer_phone_number)
        logging.debug(f"make_bulk_call_button pressed: response={response}")

# Function to fetch call logs
def call_logs():
    st.subheader("Call Logs")
    response = fetch_call_logs_api()
    logging.debug(f"fetch_call_logs_api response: {response}")

    if response and 'calls' in response:
        calls = response["calls"]
        if calls:
            df = pd.DataFrame(calls)
            logging.debug(f"Calls DataFrame: {df}")
            
            # Define the columns we want to display if they exist
            desired_columns = [
                'created_at', 'to', 'from', 'call_length', 'price', 'status', 'call_id'
            ]
            
            # Only include columns that exist in the DataFrame
            existing_columns = [col for col in desired_columns if col in df.columns]
            if existing_columns:
                df = df[existing_columns]

                # Display the table
                st.write(df)

                # Add buttons for each call to view transcript and summary
                for index, row in df.iterrows():
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button(f"View Transcript for {row['call_id']}", key=f"transcript_{row['call_id']}"):
                            st.session_state['call_id'] = row['call_id']
                            show_transcript_and_summary(row['call_id'])
                            logging.debug(f"Transcript button pressed for call_id={row['call_id']}")
                    with col2:
                        if st.button(f"View Summary for {row['call_id']}", key=f"summary_{row['call_id']}"):
                            st.session_state['call_id'] = row['call_id']
                            show_transcript_and_summary(row['call_id'])
                            logging.debug(f"Summary button pressed for call_id={row['call_id']}")
            else:
                st.warning("No recognizable columns found in the call data.")
                logging.warning("No recognizable columns found in the call data.")
        else:
            st.info("No calls found in the response.")
            logging.info("No calls found in the response.")
    else:
        st.error("Failed to fetch call logs or received an invalid response.")
        logging.error("Failed to fetch call logs or received an invalid response.")

# Function to fetch the call transcript and summary
def show_transcript_and_summary(call_id):
    url = f"https://api.bland.ai/v1/calls/{call_id}"
    headers = {"Authorization": API_KEY}
    response = requests.get(url, headers=headers)
    logging.debug(f"Fetching transcript and summary for call_id={call_id}: response={response}")

    if response.status_code == 200:
        call_details = response.json()
        logging.debug(f"call_details: {call_details}")
        concatenated_transcript = call_details.get("concatenated_transcript", "")
        summary = call_details.get("summary", "No summary available.")
        st.text_area("Transcript", concatenated_transcript, height=300)
        st.text_area("Summary", summary, height=300)
        
        # Store both transcript and summary in MongoDB
        store_transcript_and_summary(call_id, concatenated_transcript, summary)
        
        user_details = extract_user_details(concatenated_transcript)
        logging.debug(f"Extracted user_details: {user_details}")

        if user_details:
            name = user_details.get('Name', '')
            date = user_details.get('Date', '')
            time = user_details.get('Time', '')
            email = user_details.get('Email', '')
            store_in_mongodb(user_details)
            if name and date and time and email:
                meeting_link = create_event(name, date, time, email)
                logging.debug(f"Created meeting link: {meeting_link}")
                if meeting_link:
                    st.success(f"Meeting scheduled successfully! Meeting link: {meeting_link}")
                    # Store user details and meeting link in MongoDB
                    store_user_details_with_meeting_link(user_details, meeting_link)
                    # Send email with SendGrid
                    email_response = send_email_with_sendgrid(name, email, meeting_link)
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
            logging.error("Failed to extract user details.")
    else:
        st.error("Failed to fetch transcript and summary.")
        logging.error("Failed to fetch transcript and summary.")

# Function to make a single call using API
def make_single_call_api(phone_number, task, transfer_phone_number):
    headers = {"Authorization": API_KEY}
    data = {
        "phone_number": phone_number,
        "task": task,
        # "language": "de",
        "language": "en",
        "voice": "e1289219-0ea2-4f22-a994-c542c2a48a0f",
        "transfer_phone_number": transfer_phone_number
    }
    response = requests.post("https://api.bland.ai/v1/calls", data=data, headers=headers)
    logging.debug(f"make_single_call_api response: {response.json()}")
    st.write(response.json())
    return response

# Function to make bulk calls using API
def make_bulk_call_api(uploaded_file, task, transfer_phone_number):
    headers = {"Authorization": API_KEY}
    try:
        df = pd.read_csv(uploaded_file)
        logging.debug(f"Bulk call uploaded CSV DataFrame: {df}")
        if "name" in df.columns and "phone_number" in df.columns:
            for index, row in df.iterrows():
                name = row["name"]
                phone_number = row["phone_number"]
                task_prompt = task.format(name=name)
                data = {"phone_number": phone_number, "task": task_prompt,  "language": "en", "transfer_phone_number": transfer_phone_number}
                response = requests.post("https://api.bland.ai/v1/calls", data=data, headers=headers)
                logging.debug(f"Bulk Call Response for {phone_number}: {response.json()}")
                st.write(response.json())
                if response.status_code == 200:
                    call_details = response.json()
                    schedule_google_calendar(call_details)
            return response
        else:
            st.error("Columns 'name' or 'phone_number' not found in the uploaded file.")
            logging.error("Columns 'name' or 'phone_number' not found in the uploaded file.")
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

# Function to extract user details from summary using OpenAI
def extract_user_details(summary):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Extract the name, date (in YYYY/MM/DD format), time (in 24-hour format), and email from the following transcript of an interview scheduling call. Provide the information in this exact format: Name: [Name], Date: [YYYYMMDD], Time: [HH:MM], Email: [email@example.com]"},
                {"role": "user", "content": summary}
            ],
            temperature=0.7,
            max_tokens=256,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        details = response.choices[0].message.content
        logging.debug(f"OpenAI extract_user_details response: {response}")
        logging.debug(f"Extracted details from OpenAI: {details}")
        
        # Parse the response into a dictionary
        details_dict = {}
        for line in details.split(','):
            if ':' in line:
                key, value = line.split(':', 1)
                details_dict[key.strip()] = value.strip()
        
        logging.debug(f"Parsed user details: {details_dict}")

        # Ensure the year is 2024 if it's not already set to a different year
        if 'Date' in details_dict:
            date_str = details_dict['Date']
            if len(date_str) == 8:
                year = date_str[:4]
                if year == '2022':
                    date_str = '2024' + date_str[4:]
                    details_dict['Date'] = date_str

        return details_dict
    except Exception as e:
        st.error(f"Error extracting details from OpenAI: {e}")
        logging.error(f"extract_user_details Error: {e}")
        return {}

# Function to store details in MongoDB
def store_in_mongodb(details):
    try:
        if isinstance(details, dict):
            # Check if user meeting details already exist in the database
            existing_meeting = collectionSecond.find_one({
                'Name': details['Name'],
                'Email': details['Email'],
                'Date': details['Date'],
                'Time': details['Time']
            })
            if not existing_meeting:
                collectionSecond.insert_one(details)
                logging.debug("Stored user meeting details in MongoDB")
            else:
                logging.info("User meeting details with the same Name, Email, Date, and Time already exist in MongoDB")
        else:
            st.error("Failed to store details: details are not in the correct format.")
            logging.error("Failed to store details: details are not in the correct format.")
    except Exception as e:
        st.error(f"Error storing details in MongoDB: {e}")
        logging.error(f"store_in_mongodb Error: {e}")

# Function to store transcript and summary in MongoDB
def store_transcript_and_summary(call_id, transcript, summary):
    try:
        # Check if the call transcript and summary already exist in the database
        existing_call = collection.find_one({"call_sid": call_id})
        if not existing_call:
            collection.update_one(
                {"call_sid": call_id},
                {"$set": {"transcript_and_summary": {"transcript": transcript, "summary": summary}}},
                upsert=True
            )
            logging.debug("Stored transcript and summary in MongoDB")
        else:
            logging.info(f"Call details with call_id={call_id} already exist in MongoDB")
    except Exception as e:
        st.error(f"Error storing transcript and summary in MongoDB: {e}")
        logging.error(f"store_transcript_and_summary Error: {e}")

# Function to get Google Calendar service
def get_calendar_service():
    creds = None
    try:
        if os.path.exists(token_file):
            with open(token_file, 'rb') as token:
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
                with open(token_file, 'wb') as token:
                    pickle.dump(creds, token)
        logging.debug("Google Calendar service created")
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Error getting Google Calendar service: {e}")
        logging.error(f"get_calendar_service Error: {e}")

def create_event(name, date, time, email):
    try:
        # Ensure the year is 2024
        if len(date) == 8 and date[:4] != '2024':
            date = '2024' + date[4:]

        # Ensure time is correctly formatted
        if len(time) == 4:
            time = f"{time[:2]}:{time[2:]}"

        start_datetime = f'{date[:4]}-{date[4:6]}-{date[6:8]}T{time}:00'
        end_hour = str(int(time[:2]) + 1).zfill(2)
        end_datetime = f'{date[:4]}-{date[4:6]}-{date[6:8]}T{end_hour}:{time[3:]}:00'

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

        service = get_calendar_service()
        event = service.events().insert(calendarId='primary', body=event).execute()
        logging.debug(f"Event created: {event}")
        meeting_link = event.get('htmlLink')
        logging.debug(f"Generated meeting link: {meeting_link}")
        return meeting_link
    except ValueError as e:
        logging.error(f"An error occurred with date/time formatting: {e}")
        st.error("Invalid date or time format.")
        return None
    except Exception as e:
        logging.error(f"create_event Error: {e}")
        return None

# Function to schedule meeting in Google Calendar
def schedule_google_calendar(user_details):
    try:
        if 'User Name' in user_details and 'Email Address' in user_details and 'Date & Time' in user_details:
            name = user_details['User Name']
            email = user_details['Email Address']
            
            # Parse date and time from user input
            date_time_str = user_details['Date & Time']
            date_time_obj = datetime.strptime(date_time_str, '%B %d at %I %p')
            
            # Format date and time for Google Calendar
            date = date_time_obj.strftime('%Y%m%d')
            time = date_time_obj.strftime('%H:%M')
            
            # Ensure the year is 2024
            if date[:4] != '2024':
                date = '2024' + date[4:]

            meeting_link = create_event(name, date, time, email)
            logging.debug(f"Meeting link generated: {meeting_link}")
            if meeting_link:
                logging.debug(f"Meeting scheduled successfully: {meeting_link}")
                st.success("Meeting scheduled successfully!")
                st.write(f"Meeting link: {meeting_link}")
            else:
                st.error("Failed to schedule meeting in Google Calendar.")
                logging.error("Failed to schedule meeting in Google Calendar.")
        else:
            st.error(f"Insufficient details to schedule meeting in Google Calendar. Details: {user_details}")
            logging.error(f"Insufficient details to schedule meeting in Google Calendar. Details: {user_details}")
    except ValueError as e:
        st.error(f"Error parsing date/time: {e}. Please ensure the date format is 'Month Day at Hour AM/PM'")
        logging.error(f"schedule_google_calendar ValueError: {e}")
    except KeyError as e:
        st.error(f"Error extracting details from OpenAI response: {e}")
        logging.error(f"schedule_google_calendar KeyError: {e}")
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        logging.error(f"schedule_google_calendar Error: {e}")

# Function to send email using SendGrid
def send_email_with_sendgrid(name, email, meeting_link):
    try:
        message = Mail(
            from_email='digital.marketing.connection24@gmail.com',
            to_emails=email,
            subject='Interview Scheduled',
            html_content=f'<p>Dear {name},</p><p>Your interview has been scheduled. Please find the details below:</p><p><a href="{meeting_link}">Join Meeting</a></p><p>Thank you.</p>'
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logging.debug(f"SendGrid response: {response.status_code}")
        if response.status_code == 202:
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Error sending email with SendGrid: {e}")
        return False

# Function to show embedded Google Calendar
def show_meetings():
    st.subheader("Scheduled Meetings")
    calendar_url = CALENDAR_URL;
    components.iframe(calendar_url, width=800, height=600, scrolling=True)

# Function to show name, transcript, and summary
def show_name_transcript_summary():
    st.subheader("Name, Transcript & Summary")
    
    # Fetch data from MongoDB
    data = list(collection.find({}, {'call_sid': 1, 'transcript_and_summary': 1}))
    
    if not data:
        st.info("No data available.")
        logging.info("No data available.")
        return
    
    # Create DataFrame
    df = pd.DataFrame(data)
    df['index'] = range(1, len(df) + 1)
    df = df.rename(columns={'call_sid': 'SID'})
    
    # Display table
    st.table(df[['index', 'SID']])
    
    # Add buttons for each row
    for index, row in df.iterrows():
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"Show Transcript {row['index']}", key=f"transcript_{row['SID']}"):
                show_popup("Transcript", row['transcript_and_summary']['transcript'])
                logging.debug(f"Show Transcript button pressed for SID={row['SID']}")
        with col2:
            if st.button(f"Show Summary {row['index']}", key=f"summary_{row['SID']}"):
                show_popup("Summary", row['transcript_and_summary']['summary'])
                logging.debug(f"Show Summary button pressed for SID={row['SID']}")

# Function to show popup
def show_popup(title, content):
    st.subheader(title)
    st.text_area("", value=content, height=300)

# Function to store user details and meeting link in MongoDB
def store_user_details_with_meeting_link(user_details, meeting_link):
    try:
        user_details['Meeting Link'] = meeting_link
        if isinstance(user_details, dict):
            # Check if user details already exist in the database
            existing_user = user_details_collection.find_one({
                'Name': user_details['Name'],
                'Email': user_details['Email'],
                'Date': user_details['Date'],
                'Time': user_details['Time']
            })
            if not existing_user:
                user_details_collection.insert_one(user_details)
                logging.debug("Stored user details with meeting link in MongoDB")
            else:
                logging.info("User details with the same Name, Email, Date, and Time already exist in MongoDB")
        else:
            st.error("Failed to store details: details are not in the correct format.")
            logging.error("Failed to store details: details are not in the correct format.")
    except Exception as e:
        st.error(f"Error storing user details with meeting link in MongoDB: {e}")
        logging.error(f"store_user_details_with_meeting_link Error: {e}")

# Function to display user details in dashboard
def display_user_details():
    st.subheader("User Details")
    
    # Fetch data from MongoDB
    data = list(user_details_collection.find({}, {'_id': 0}))
    
    if not data:
        st.info("No user details available.")
        logging.info("No user details available.")
        return
    
    # Create DataFrame
    df = pd.DataFrame(data)
    df['index'] = range(1, len(df) + 1)
    
    # Rename columns for display
    df = df.rename(columns={
        'Name': 'Name',
        'Email': 'Email',
        'Date': 'Date',
        'Time': 'Time',
        'Meeting Link': 'Meeting Link'
    })
    
    # Display table
    st.table(df[['index', 'Name', 'Email', 'Date', 'Time', 'Meeting Link']])

if __name__ == "__main__":
    main()
