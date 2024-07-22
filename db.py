import pymongo

# MongoDB connection URL
MONGO_URL = "mongodb+srv://sachinparmar0246:2nGATJVDEwDZzaA8@cluster0.c25rmsz.mongodb.net"

# Initialize MongoDB client
client = pymongo.MongoClient(MONGO_URL)

# Database name
db = client["call_data"]

# Collection name
collection = db["call_summaries"]
collectionSecond = db["userMettingDetails"]
user_details_collection = db["user_details"]  # New collection for user details and meeting link
