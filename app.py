
#gcloud auth application-default login
#gcloud config set project PROJECT-ID


# things to do 
# [bug] extract button requires two times hit - something to do with session
# [bug] need a refresh/restart button, that clears all the session states. after one link, it doesn't take new
# [bug] Combine all TL:Drs into one single one. Lot of oevralapping info 
# [feature] add option to select "upvote" count from user side 
# [feature] make "detailed analysis" optional and run when user hits the button. 
# [feature] the app is slow right now. Need to make it fast. Async has wait=2
# [feature] tune the prompt 
# [feature] move secrets to secrets.toml 
# [feature] modularize the code
# [feature] fix the sessions.state and flow 


import streamlit as st
from google.cloud import aiplatform as vertexai
import time
from vertexai.generative_models import (
    GenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    Part,
)
import praw
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
# import nest_asyncio  # Install: !pip install nest_asyncio
import asyncpraw
import asyncprawcore
from rich import print as rich_print
from rich.markdown import Markdown as rich_Markdown
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
# import nest_asyncio  # Install: !pip install nest_asyncio
import asyncpraw
import asyncprawcore

# --- Secret Management ---
PROJECT_ID = 
LOCATION = 
CLIENT_ID = 
CLIENT_SECRET = 
USER_AGENT = 
MODEL_ID = 

import vertexai

vertexai.init(project=PROJECT_ID, location=LOCATION)

# State Initialization
if 'post_index_db' not in st.session_state:
    st.session_state['post_index_db'] = pd.DataFrame()
if  'reddit_links'  not in st.session_state:
    st.session_state['reddit_links'] = str
if 'reddit_links_list' not in st.session_state:
    st.session_state['reddit_links_list'] = []
if 'debug_toggle' not in st.session_state:
    st.session_state['debug_toggle'] = True
if 'comment_reply_context' not in st.session_state:
    st.session_state['comment_reply_context'] = {}
if 'sentiment_analysis' not in st.session_state:
    st.session_state['sentiment_analysis'] = str
if 'find_sentiment_button_toggle' not in st.session_state:
    st.session_state['find_sentiment_button_toggle'] = False


# --- Helper Functions ---

async def extract_comment_thread(comment, max_replies_per_comment):
    await comment.refresh()  # Ensure replies are up-to-date
    replies = []
    async for reply in comment.replies:  # Iterate through replies asynchronously
        if reply.author is not None and reply.body is not None:  # Exclude deleted replies
            replies.append({
                "Reply Body": reply.body,
                "Reply Upvotes": reply.score,
            })
        if len(replies) >= max_replies_per_comment:  # Limit replies if needed
            break
    return {
        "Comment ID": comment.id,
        "Comment Body": comment.body,
        "Comment Upvotes": comment.score,
        "Replies": replies,
    }

async def process_submission(reddit, submission_id, max_comments_per_post, max_replies_per_comment):
    try:
        submission = await reddit.submission(id=submission_id)
        await submission.comments.replace_more(limit=max_comments_per_post)
        # Extract additional submission information
        post_id = submission.id
        post_title = submission.title
        post_text = submission.selftext
        post_date = pd.Timestamp(submission.created_utc, unit='s')
        # post_views = submission.view_count  # Unfortunately, Reddit API doesn't provide view counts anymore

        comment_data = []

        async for comment in submission.comments:
            comment_info = await extract_comment_thread(comment, max_replies_per_comment)
            # print(comment_info)
            comment_data.append(comment_info)

        for comment_dict in comment_data:
            comment_dict['Post ID'] = post_id
            comment_dict['Post Title'] = post_title
            comment_dict['Post Text'] = post_text
            comment_dict['Post Date'] = post_date
            # comment_dict['Post Views'] = post_views

        return pd.DataFrame(comment_data)

        # return pd.DataFrame(comment_data)

    except asyncprawcore.exceptions.NotFound:
        print(f"Submission {submission_id} not found (deleted or removed).")
        return pd.DataFrame()
    except asyncprawcore.exceptions.RequestException as e:
        print(f"Error processing submission {submission_id}: {e}")
        return pd.DataFrame()

async def process_submissions(links, client_id, client_secret, user_agent, max_comments_per_post=None, max_replies_per_comment=None):
    reddit = asyncpraw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )

    all_dataframes = []
    for link in links:
        submission_id = link.split("/")[-2]
        df = await process_submission(reddit, submission_id, max_comments_per_post, max_replies_per_comment)
        all_dataframes.append(df)
        await asyncio.sleep(2)  # Rate limiting (adjust as needed)

    await reddit.close()  # Important to close the connection

    return pd.concat(all_dataframes, ignore_index=True)

async def main_reddit_logic(reddit_post_link_list):
    client_id = CLIENT_ID
    client_secret = CLIENT_SECRET
    user_agent = USER_AGENT
    max_comments_per_post = 5
    max_replies_per_comment = 2

    return await process_submissions(reddit_post_link_list, client_id, client_secret,
                                     user_agent, max_comments_per_post,
                                     max_replies_per_comment)

def get_analyze_routine():
    if not st.session_state['post_index_db'].empty:
        if st.button("Analyze"):
            st.write("analyzing....")

def get_gemini(prompt):
  model = GenerativeModel(
    MODEL_ID,
    # system_instruction=[
    #     system_instruction,
    # ],
)

  # Set model parameters
  generation_config = GenerationConfig(
      temperature=0.9,
      top_p=1.0,
      top_k=32,
      candidate_count=1,
      max_output_tokens=8192,
  )

  # Set contents to send to the model
  contents = [prompt]

  # Set safety settings
  safety_settings = {
      HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
      HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
      HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
      HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
  }

  # Prompt the model to generate content
  response = model.generate_content(
    contents,
    generation_config=generation_config,
    safety_settings=safety_settings,
  )

  return response.text


def get_comment_reply_pair(index_db, max_vote_filter):
    comment_reply_pair = {}
    for index, row in index_db.iterrows():
        if row['Comment Upvotes'] > max_vote_filter:
            comment_id = row['Comment ID']
            comment_body = row['Comment Body']
            comment_upvote = row['Comment Upvotes']
            comment_reply_pair[comment_id] = {}
            comment_reply_pair[comment_id]['comment_body'] = comment_body
            comment_reply_pair[comment_id]['comment_upvote'] = comment_upvote
            replies = []
            for index, reply in enumerate(row['Replies']):
                reply_number = index+1
                single_reply_dict = {}
                single_reply_dict[reply_number] ={}
                single_reply_dict[reply_number]['reply_body'] = reply['Reply Body']
                single_reply_dict[reply_number]['reply_upvote'] = reply['Reply Upvotes']
                replies.append(single_reply_dict)
            comment_reply_pair[comment_id]['replies'] = replies
    return comment_reply_pair

def get_overall_sentiment_report(context):
  prompt = f"""Instruction: Synthesize the following Sentiment and Emotion Analysis reports into a comprehensive, language-based summary, highlighting key sentiments, emotions, and actionable insights. Reference specific phrases and comment IDs to support your analysis.
  Input Context Data Structure: {{ "comment_id":

      {{
          "comment_body": "comment text",
          "comment_upvote": "total votes for the comment",
          "replies":  [
              1: {{
                  "reply_body": "reply text",
                  "reply_upvote": total votes for the reply
              }},
              2: {{
                  "reply_body": "reply text",
                  "reply_upvote": "total votes for the reply"
              }}
          ]
      }}


  }}

  Context:{context}

  Output Format:

  1. Overall Sentiment and Emotion Summary:
      - A descriptive summary of the prevailing sentiment (positive, negative, neutral) and the dominant emotions (frustration, confusion, delight) across all threads.
      - Cite examples from comments to illustrate the overall tone and emotional landscape (e.g., "The majority of users expressed positive sentiments about the product, with enthusiastic comments like 'This is amazing!' (Comment ID 123). However, there were instances of frustration regarding specific features, as seen in Comment ID 456: 'I can't believe this doesn't work!'").

  2. Key Themes, Concerns, and Emotional Triggers:
      - Identify the most prominent themes and recurring topics in the comments and replies, highlighting any emotions associated with them.
      - Discuss the specific aspects or features that users frequently mentioned, along with their associated sentiments and emotional responses.
      - Analyze the most common concerns or pain points raised by users, focusing on the emotions they evoke (e.g., "The lack of documentation was a major source of frustration for many users, as evidenced by comments like 'I'm completely lost!' (Comment ID 789)").

  3. Notable Observations and Insights:
      - Highlight any particularly insightful or noteworthy comments or patterns, emphasizing the emotional impact they convey.
      - Discuss any emerging trends or shifts in sentiment and emotions across the threads.
      - Identify any potential areas for further investigation or analysis, focusing on areas where emotions are particularly strong or mixed.

  4. Actionable Recommendations:
      - Prioritize actionable recommendations based on the sentiment and emotion analysis, considering both the frequency and intensity of specific feelings.
      - Suggest specific ways to address user concerns or improve the product, taking into account the emotional impact of these issues.
      - Offer strategies for leveraging positive emotions to enhance marketing or communication efforts, and for mitigating negative emotions to improve customer satisfaction.    """
  return get_gemini(prompt)

def get_overall_friction_point_report(context):
  # if row['Comment Upvotes'] > max_vote_filter:
  prompt = f"""Instruction: Synthesize the following Friction Points reports into a comprehensive, language-based summary, highlighting key issues and their impact. Reference specific phrases and comment IDs to support your analysis.
  Input Context Data Structure: {{ "comment_id":

    {{
        "comment_body": "comment text",
        "comment_upvote": "total votes for the comment",
        "replies":  [
            1: {{
                "reply_body": "reply text",
                "reply_upvote": total votes for the reply
            }},
            2: {{
                "reply_body": "reply text",
                "reply_upvote": "total votes for the reply"
            }}
        ]
    }}


}}

  Context:{context}

  Output Format:

  1. Overview of Key Friction Points:
      - A concise summary of the most frequently encountered friction points or issues across all threads.
      - Highlight any dominant issues that appear repeatedly in the discussions.
      - Provide examples of direct quotes and comment IDs where these issues are mentioned (e.g., "The 'login process' was identified as a major friction point in Comment ID 123: 'I keep getting error messages when trying to log in...'").

  2. Severity Assessment:
      - Summarize the overall severity of the friction points identified, categorizing them as High, Medium, or Low.
      - Provide examples of specific comments or quotes that illustrate the impact of each friction point on the user experience (e.g., "Comment ID 456 highlights the high severity of the issue: 'This bug completely prevents me from using the product...'").

  3. Frequency Analysis:
      - Identify the most frequently mentioned friction points, citing the number of times they were raised in the threads.
      - Discuss any patterns or trends in the frequency of certain issues, noting any potential correlations with user demographics or specific product usage scenarios.

  4. Actionable Recommendations:
      - Prioritize the friction points based on their severity and frequency.
      - Provide specific recommendations for addressing each friction point, referencing relevant user feedback and comment IDs.
      - Suggest potential solutions or improvements to mitigate the impact of these issues on the user experience.    """
  return get_gemini(prompt)

def get_overall_feature_request_report(context):
  # if row['Comment Upvotes'] > max_vote_filter:
  prompt = f"""Instruction: Synthesize the following Feature Request reports into a comprehensive, language-based summary, highlighting key suggestions and their potential impact. Reference specific phrases and comment IDs to support your analysis.
  Input Context Data Structure: {{ "comment_id":

    {{
        "comment_body": "comment text",
        "comment_upvote": "total votes for the comment",
        "replies":  [
            1: {{
                "reply_body": "reply text",
                "reply_upvote": total votes for the reply
            }},
            2: {{
                "reply_body": "reply text",
                "reply_upvote": "total votes for the reply"
            }}
        ]
    }}


}}

  Context:{context}

  Output Format:

  1. Overview of Key Feature Requests:
      - A concise summary of the most frequently requested features or suggestions across all threads.
      - Highlight any dominant feature requests that appear repeatedly in the discussions.
      - Provide examples of direct quotes and comment IDs where these requests are mentioned (e.g., "The ability to 'export data in CSV format' was a common request, as seen in Comment ID 987: 'It would be great if we could export data...'").

  2. Use Case Analysis:
      - For each key feature request, summarize the associated use cases or scenarios where the feature would be beneficial, if mentioned by users.
      - Cite specific comments and quotes that illustrate these use cases (e.g., "Comment ID 654 suggests a use case for the 'data export' feature: 'I need to export data for further analysis in Excel...'").

  3. Potential Impact Assessment:
      - Evaluate the potential impact of each feature request, categorizing it as High, Medium, or Low based on the perceived value or benefit it would bring to users.
      - Reference comments that provide insights into the potential impact, either explicitly or implicitly (e.g., "The 'dark mode' feature request in Comment ID 321 received several upvotes, indicating a high demand and potential impact").

  4. Additional Insights:
      - Identify any recurring themes or patterns in the feature requests.
      - Highlight any potential connections or dependencies between different requests.
      - Discuss any emerging trends or shifts in user preferences regarding features.

  5. Actionable Recommendations:
      - Prioritize the feature requests based on their frequency, potential impact, and alignment with the product roadmap.
      - Provide specific recommendations for implementing or prioritizing these features, referencing relevant user feedback and comment IDs.
      - Suggest ways to communicate with users about upcoming feature development or improvements.  return get_gemini(prompt)
  """
  return get_gemini(prompt)

def get_overall_competitor_report(context):
  # if row['Comment Upvotes'] > max_vote_filter:
  prompt = f"""Instruction: Synthesize the following Competitor Analysis reports into a comprehensive, language-based summary, highlighting key competitor mentions and their context. Reference specific phrases and comment IDs to support your analysis.
  Input Context Data Structure: {{ "comment_id":

    {{
        "comment_body": "comment text",
        "comment_upvote": "total votes for the comment",
        "replies":  [
            1: {{
                "reply_body": "reply text",
                "reply_upvote": total votes for the reply
            }},
            2: {{
                "reply_body": "reply text",
                "reply_upvote": "total votes for the reply"
            }}
        ]
    }}


}}

  Context:{context}

  Output Format:

  Output Format:

  1. Overview of Competitor Mentions:
      - A concise summary of the most frequently mentioned competitors across all threads.
      - Highlight any dominant competitors that appear repeatedly in the discussions.
      - Provide examples of direct quotes and comment IDs where these competitors are mentioned (e.g., "Competitor X was mentioned several times, as seen in Comment ID 543: 'I've been using Competitor X, but I'm considering switching...'").

  2. Sentiment Analysis of Competitor Mentions:
      - For each competitor mentioned, summarize the associated sentiment (positive, negative, neutral) based on the comments and replies.
      - Provide examples of specific phrases or quotes that illustrate the sentiment towards each competitor, along with their respective comment IDs (e.g., "Comment ID 234 expresses a positive sentiment towards Competitor Y: 'Their customer support is top-notch!'").

  3. Feature Comparisons:
      - Identify any instances where users compare your product or features to those of competitors.
      - Summarize these comparisons, highlighting any strengths or weaknesses of your product relative to competitors, as perceived by users.
      - Cite specific comments and quotes that contain these comparisons (e.g., "Comment ID 789 compares Feature A to a similar feature in Competitor Z: 'Feature A is much more customizable than...'").

  4. Competitive Landscape Analysis:
      - Discuss the overall competitive landscape based on the comments and replies.
      - Identify any key trends or patterns in how users perceive your product in relation to competitors.
      - Highlight any potential threats or opportunities based on the competitor analysis.

  5. Actionable Recommendations:
      - Provide specific recommendations for product development, marketing, or communication strategies based on the competitor analysis.
      - Suggest ways to differentiate your product or address areas where competitors are perceived as stronger.
      - Identify potential opportunities to leverage competitor weaknesses or highlight your product's unique advantages.
    """
  return get_gemini(prompt)


def get_tldr_persona_based_report(context):
  # if row['Comment Upvotes'] > max_vote_filter:
  prompt = f"""Task: Create persona and profile specific TL:DRs for product analysis on reddit comments.
Instructions:
- Make sure that the Tl:DRs are customised and aligned with job profile and expectations based on persona
- All points should be bulleted, precise and easy to understand
- Make sure to have actionable insights which is easy to follow
- Mention both positive and negative aspect of the analysis

Personas:
1) Developer Relations Leadership 
2) Developer Relations Content & Asset Developers
3) Product Managers

Analysis:
  {context}
  """
  return get_gemini(prompt)


# --- App Title ---
st.set_page_config(
    page_title="Reddit Post Analysis",
    page_icon=":mag:",
    layout="centered",
)

st.markdown(
    """
    <style>
    .custom-title {
        font-size: 3em;
        text-align: center; /* Center the text */ 
    }
    .custom-title span {
        color: #ff4500; 
    }
    </style>
    <h1 class="custom-title">Friction Logging with <span>Reddit</span></h1>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <style>
    .disclaimer {
        font-size: 0.9em; 
        color: #555; 
        text-align: center; /* Center the text */
    }
    .disclaimer-emoji { 
        font-size: 1.2em; 
        margin-right: 5px; 
    }
    </style>
    <p class="disclaimer">
        <span class="disclaimer-emoji">⚠️</span>
        This app is tuned for product friction logging and not general social media sentiment analysis. 
        Only works for reddit input links (multiple, single as well) that are talking about some products.
        <span class="disclaimer-emoji">⚠️</span>
    </p>
    """,
    unsafe_allow_html=True,
)

# --- Input & Pre-processing ---
# test links:
# https://www.reddit.com/r/google/comments/1axn2gi/100_honest_take_on_google_gemini/
# https://www.reddit.com/r/singularity/comments/1bk8uxw/you_can_now_use_gemini_15_pro_for_1m_tokens_for/
# https://www.reddit.com/r/Bard/comments/1bc3nw9/this_gemini_15_in_ai_studio_is_real
# https://www.reddit.com/r/Bard/comments/1csugzh/gemini_15_pro_on_geminigooglecom_and_ai_studio
# https://www.reddit.com/r/google/comments/1axn2gi/100_honest_take_on_google_gemini
# https://www.reddit.com/r/singularity/comments/1alstf8/gemini_advanced
# https://www.reddit.com/r/google/comments/1dr7sqh/gemini_is_just_stupid


# --- Main Page ---

def initialize_session_states():
    """Initializes all session states."""
    st.session_state.setdefault('post_index_db', pd.DataFrame())
    st.session_state.setdefault('reddit_links', str)
    st.session_state.setdefault('reddit_links_list', [])
    st.session_state.setdefault('debug_toggle', True)
    st.session_state.setdefault('comment_reply_context', {})
    st.session_state.setdefault('sentiment_analysis', str)
    st.session_state.setdefault('comment_extraction_process', False)
    st.session_state.setdefault('find_sentiment_button_toggle', False)
    st.session_state.setdefault('run_analysis_button_toggle', False)
    st.session_state.setdefault('tldr_sentiment', str)
    st.session_state.setdefault('tldr_sentiment_button_toggle', False)
    st.session_state.setdefault('find_sentiment_button_toggle', False)
    st.session_state.setdefault('friction_analysis', str)
    st.session_state.setdefault('feature_analysis', str)
    st.session_state.setdefault('competitor_analysis', str)
    st.session_state.setdefault('tldr_friction', str)
    st.session_state.setdefault('tldr_feature', str)
    st.session_state.setdefault('tldr_competition', str)
    st.session_state.setdefault('comment_analysis_with_gemini', False)
    
def get_reddit_links_input():
    """Gets Reddit links input from the user and updates the session state."""

    st.session_state['reddit_links'] = st.text_area("Enter Reddit post links (one per line)")
    with st.expander("Click for Sample Reddit Links"):
        st.code("""
        https://www.reddit.com/r/google/comments/1axn2gi/100_honest_take_on_google_gemini/
        https://www.reddit.com/r/singularity/comments/1bk8uxw/you_can_now_use_gemini_15_pro_for_1m_tokens_for/
        https://www.reddit.com/r/Bard/comments/1bc3nw9/this_gemini_15_in_ai_studio_is_real
        https://www.reddit.com/r/Bard/comments/1csugzh/gemini_15_pro_on_geminigooglecom_and_ai_studio
        https://www.reddit.com/r/google/comments/1axn2gi/100_honest_take_on_google_gemini
        https://www.reddit.com/r/singularity/comments/1alstf8/gemini_advanced
        https://www.reddit.com/r/google/comments/1dr7sqh/gemini_is_just_stupid
        """, language=None, )  # language=None to avoid syntax highlighting


    if st.session_state['reddit_links']:
        link_list = st.session_state['reddit_links'].strip().split("\n")

        # Remove trailing slashes and empty lines
        st.session_state['reddit_links_list'] = [
            link.rstrip("/")  # Remove trailing slash if present
            for link in link_list 
            if link.strip()  # Filter out empty lines
        ]

    else:
        st.write("You have not entered any link")


def extract_comments():
    """Extracts comments from Reddit links if the index is empty and updates the session state."""
    if st.session_state['reddit_links_list'] and st.session_state['post_index_db'].empty:
        with st.spinner("Extracting comments and replies to build index..."):
            st.session_state['post_index_db'] = asyncio.run(main_reddit_logic(st.session_state['reddit_links_list']))
            st.session_state['comment_reply_context'] = get_comment_reply_pair(st.session_state['post_index_db'], max_vote_filter=50)
            st.write("Done with Comment, Reply and other metadata extraction.....")
    else:
        if not st.session_state['reddit_links_list']:
            st.write("You have not provided any links..")
        else:
            st.write("Post is already indexed...")
            st.write(st.session_state['post_index_db'])
            


def main():
    initialize_session_states()  # Initialize states at the beginning

    get_reddit_links_input()
    
    if st.button("Extract comments"):
        extract_comments()
        st.session_state['comment_extraction_process'] = True
    
    if not st.session_state['post_index_db'].empty and st.session_state['comment_extraction_process']:
        st.write("Here's all the comments and reply:")
        st.write(st.session_state['post_index_db'])
        
    if st.session_state['comment_extraction_process']:
        if 'run_analysis_button_toggle' not in st.session_state:  # Initialize the flag if not present
            st.session_state['run_analysis_button_toggle'] = False
        if st.button("Run Analysis") and not st.session_state['run_analysis_button_toggle']:
            st.session_state['run_analysis_button_toggle'] = True
            with st.spinner("Asking Gemini to analyize the overall comment-reply data...This may take time...."):
                #overall post
                st.session_state['sentiment_analysis'] = get_overall_sentiment_report(st.session_state['comment_reply_context'])
                st.session_state['friction_analysis']  = get_overall_friction_point_report(st.session_state['comment_reply_context'])
                st.session_state['feature_analysis'] = get_overall_feature_request_report(st.session_state['comment_reply_context'])
                st.session_state['competitor_analysis'] = get_overall_competitor_report(st.session_state['comment_reply_context'])
                #Tl:Dr
                st.session_state['tldr_sentiment'] = get_tldr_persona_based_report(st.session_state['sentiment_analysis'])
                st.session_state['tldr_friction'] = get_tldr_persona_based_report(st.session_state['friction_analysis'])
                st.session_state['tldr_feature'] = get_tldr_persona_based_report(st.session_state['feature_analysis'])
                st.session_state['tldr_competition'] = get_tldr_persona_based_report(st.session_state['competitor_analysis'])
                
                
                st.write("Gemini has done the hardowrk...Enjoy the analysis..")
                
                st.session_state['comment_analysis_with_gemini'] = True
        
    if st.session_state['comment_analysis_with_gemini']:
        analyze_choice_tab1, analyze_choice_tab2 = st.tabs(["TL:Dr's", "Detailed Analysis"])

        with analyze_choice_tab1:
            tldr_sentiment, tldr_friction, tldr_feature, tldr_competition = st.tabs(["Sentiment TL;DR",
                                                                                    "Friction Points TL;DR",
                                                                                    "Feature Request TL;DR",
                                                                                    "Competitor Analysis TL;DR"])

            
            with tldr_sentiment:
                st.markdown(st.session_state['tldr_sentiment'])
            with tldr_friction:
                st.markdown(st.session_state['tldr_friction'])
            with tldr_feature:
                st.markdown(st.session_state['tldr_feature'])
            with tldr_competition:
                st.markdown(st.session_state['tldr_competition'])


        with analyze_choice_tab2:
            analysis_sentiment, analysis_friction, analysis_feature, analysis_competitor = st.tabs(["Sentiment", 
                                                                                                    "Friction Points", 
                                                                                                    "Feature Request",
                                                                                                    "Competitor Analysis"])

            with analysis_sentiment:
                st.markdown(st.session_state['sentiment_analysis'])
            with analysis_friction:
                st.markdown(st.session_state['friction_analysis'])
            with analysis_feature:
                st.markdown(st.session_state['feature_analysis'])
            with analysis_competitor:
                st.markdown(st.session_state['competitor_analysis'])
            
        

if __name__ == "__main__":
    main()

# # State Initialization
# if 'post_index_db' not in st.session_state:
#     st.session_state['post_index_db'] = pd.DataFrame()
# if  'reddit_links'  not in st.session_state:
#     st.session_state['reddit_links'] = str
# if 'reddit_links_list' not in st.session_state:
#     st.session_state['reddit_links_list'] = []
# if 'debug_toggle' not in st.session_state:
#     st.session_state['debug_toggle'] = True
# if 'comment_reply_context' not in st.session_state:
#     st.session_state['comment_reply_context'] = {}
# if 'sentiment_analysis' not in st.session_state:
#     st.session_state['sentiment_analysis'] = str
# if 'find_sentiment_button_toggle' not in st.session_state:
#     st.session_state['find_sentiment_button_toggle'] = False

# st.session_state['reddit_links'] = st.text_area("Enter Reddit post links (one per line)")
# if st.session_state['reddit_links']:
#     link_list = st.session_state['reddit_links'].strip().split("\n")  # Split on newlines
#     st.session_state['reddit_links_list'] = [link.strip() for link in link_list if link.strip()]  # Clean up extra spaces and remove empty lines
#     if st.session_state['debug_toggle']:
#         st.write("Your Reddit  Link List:")
#         st.write(st.session_state['reddit_links_list'])  # Display the list in a formatted way
# else:
#     st.write("You have not entered any link")

# if st.button("Extract comments"):
#     if st.session_state['reddit_links_list']:
#         # Pre-processing with progress bar
#         if st.session_state['post_index_db'].empty:
#             with st.spinner("Extracting comments and replies to build index..."):
#                 st.session_state['post_index_db'] = asyncio.run(main_reddit_logic(st.session_state['reddit_links_list']))
#                 st.write("Done with Comment, Reply and other metadata extraction.....")
#                 # get_analyze_routine()
#                 if st.session_state['debug_toggle']:
#                     st.write(st.session_state['post_index_db'])
#         else:
#             st.write("Post is already indexed...")
#             st.write(st.session_state['post_index_db'])
#             # get_analyze_routine()
#     else:
#         st.write("You have not provided any links..")

# if not st.session_state['post_index_db'].empty:
#     if 'run_analysis_button_toggle' not in st.session_state:  # Initialize the flag if not present
#         st.session_state['run_analysis_button_toggle'] = False
#     if st.button("Run Analysis") and not st.session_state['run_analysis_button_toggle']:
#         st.session_state['run_analysis_button_toggle'] = True
#         analyze_choice_tab1, analyze_choice_tab2 = st.tabs(["Individual Analysis", "TL:Dr's"])

#         with analyze_choice_tab1:
#             tab1, tab2, tab3, tab4, tab5 = st.tabs(["Sentiment", "Topic Model", "Friction Points", "Feature Request", "Competitor Analysis"])

#             with tab1:
#                 if 'find_sentiment_button_toggle' not in st.session_state:  # Initialize the flag if not present
#                     st.session_state['find_sentiment_button_toggle'] = False

#                 if st.button("Find Sentiment") and not st.session_state['find_sentiment_button_toggle']:
#                     st.session_state['find_sentiment_button_toggle'] = True
#                     with st.spinner("Asking Gemini to analyze sentiment....."):
#                         try:
#                             st.session_state['comment_reply_context'] = get_comment_reply_pair(st.session_state['post_index_db'], max_vote_filter=50)
#                             st.session_state['sentiment_analysis'] = get_overall_sentiment_report(st.session_state['comment_reply_context'])
#                             st.markdown(st.session_state['sentiment_analysis'])
#                         except Exception as e:  # Add error handling to catch exceptions
#                             st.error(f"Error during sentiment analysis: {e}")
#                         finally:
#                             st.session_state['find_sentiment_button_toggle'] = False
#             with tab2:
#                 st.write("coming soon")
#             with tab3:
#                 st.write("coming soon")
#             with tab4:
#                 st.write("coming soon")
#             with tab5:
#                 st.write("coming soon")

#         with analyze_choice_tab2:
#             st.write("coming soon.")








