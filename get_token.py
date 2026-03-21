from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_ANON_KEY"],
)

email = input("Email: ").strip()
password = input("Password: ").strip()

response = supabase.auth.sign_in_with_password({
    "email": email,
    "password": password,
})

session = response.session
user = response.user

print("\nUSER ID:")
print(user.id)

print("\nACCESS TOKEN:")
print(session.access_token)