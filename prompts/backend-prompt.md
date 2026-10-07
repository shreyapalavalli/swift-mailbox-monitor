Executive Summary

Currently, SWIFT mailbox monitoring is performed manually by operations users.

Incoming messages received from SWIFT platform are reviewed, classified, and actioned based on predefined business rules. This results in significant manual effort, risk of missed messages, delayed processing, and operational inefficiencies.

SWIFT email box is primarily monitored for SWIFT messages sent to SGNY (acting as a correspondent), including cancellation requests, amendments, and D/A requests on same day. It is also used to manage cases where a valid ABA number is unavailable. In such situations, SGNY contacts the remitter to obtain the correct ABA details, and the remitter's responses are received and monitored through this mailbox.

Current Process:

Incoming SWIFT messages are received in the shared SWIFT mailbox.

Operations analysts manually monitor the mailbox throughout the day.

Since these messages are received with the standard subject line, each incoming message is opened and reviewed individually.

Analysts identify key SWIFT message attributes, including:

1)Message Type (MT/MX)

2)Payment Reference

3)Business Content

4)Cancellation Request

5)Amendment Request

6)Call back Request

-Messages with references starting with "SGU" are identified and routed to the CST Team (For our purposes, we will keep this as a dummy mailbox with ID as shreyapalavalli@gmail.com).

-Cancellation messages are manually reviewed and marked as Read(action to be performed by our backend), except camt.056 messages, which require further action (Examples of these types of SWIFT message emails are provided).

-Amendment requests are manually identified and prioritized for processing (Our backend should classify these swifts as priority and an alert should be sent to the frontend with the key attributes which users can use to quickly respond).

-Callback messages with references starting with "FT/INV" are manually reviewed and responded to.


-Any exceptions or action-required messages are manually tracked and managed.

Operational Volumes:

3,000+ SWIFT messages processed monthly

200+ SWIFT messages received daily

High volume of repetitive manual reviews and classifications

Significant effort required for monitoring, routing, and action management

Increased risk of delayed processing due to growing message volumes

Requirement:

Operations teams currently spend considerable time reviewing and processing SWIFT messages manually. This approach is repetitive, resource-intensive, and prone to human error, resulting in operational inefficiencies and increased risk of missed or delayed actions.

The proposed solution should automatically read, understand, classify, prioritize, and action SWIFT messages based on predefined business rules while providing intelligent recommendations for exception handling.

The objective is to reduce risk, manual effort, improve operational efficiency, strengthen controls, and enhance customer service through intelligent automation.

Key Automation Scenarios:

Automatically identify messages with references starting with "SGU" and mark them as Read since they belong to the CST Team.

Automatically identify and classify cancellation messages.

Automatically mark cancellation messages as Read, except for camt.056 messages that require analyst intervention.

Automatically identify amendment requests and route them for priority action.

Automatically identify and respond to callback messages with references starting with "FT/INV".

Extract key SWIFT message information, including:

Message Type (MT/MX)

Payment Reference

Business Purpose

Request Category

-Required Actions:

1) Build out a complete FAST API backend with Python using SQL lite as the DB and Flask for frontend.
2) You have full access to my system and can use Microsoft Graph API calls to perform all necessary actions (Reading, marking as Read, rerouting to shreyapalavalli@gmail.com)
3) for all swifts that require action and cannot simply be marked as read, from those swifts, the backend should collect the key info and store then in DB using refernece as the key so that the frontend can pick them up in real time and display those metrics to the user
4) The Mailbox (MTheadsYI@outlook.com) already has some swift messaged which you need to use as examples for your classification module
5) Use NLP to read the JSONS from the mailbox which you know how to do. Use only inbuilt Python NLP libraries to classify SWIFTS and perform the necessary actions on the emails
6) Create another script that simply generates dummy Swifts like those already present in mailbox and continuosly keeps mailing them to "MTheadsYI@outlook.com" from "vishnuprakash156@gmail.com"
7) Be very thorough about the "Key Automation Scenarios" section as that is what tells what actions to be performed on what kind of emails.

