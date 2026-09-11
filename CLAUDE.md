# Project Overview
An agentic customer support system for a Chinese restaurant that assists customers with menu questions, ingredient and allergy inquiries, order placement, and refund requests.

This project is still in development.

# Plan Architecture
- Router Agent:
    - Purpose: Entry point for all customer interactions.
    - This agent will route the user request to the correct specialized agent to assist them. Additionally, it should give a sentiment analysist that will only be given to the refund agent. 

- Order Agent:
    - Purpose: Handles general customer support and ordering.
    - This agent will help the customer with ordering and answering any questions related to the menu.

- Refund Agent:
    - Purpose: Handles customer complaints and refunds request as according to restaurant policy.
    - The idea for this agent is to handle customer interaction post orders. 

- Ticket Summary Agent:
    - Purpose: Produces the final support ticket summary artifact.
    - Two types of tickets: refund ticket and order / support ticket.

# Tech Stack
- LangGraph
- LangSmith
- PyTest
- Python
- SQLite