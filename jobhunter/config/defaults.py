"""Shared, environment-independent defaults.

Defaults live here rather than in examples and consumers. ``settings`` is the only
module that reads environment variables for application behavior.
"""

from jobhunter.models import ScoringRulesConfig

CORE_TARGET_ROLES = tuple(
    """
Junior Software Engineer
Software Engineer I
Associate Software Engineer
Graduate Software Engineer
New Grad Software Engineer
Software Engineer
Junior Software Developer
Associate Software Developer
Software Developer
Python Developer
Junior Python Developer
Backend Developer
Backend Engineer
Junior Backend Developer
Full Stack Developer
Full Stack Engineer
Junior Full Stack Developer
Automation Engineer
Junior Automation Engineer
Test Automation Engineer
QA Automation Engineer
Junior Automation QA Engineer
Software QA Engineer
Machine Learning Engineer
Junior Machine Learning Engineer
ML Engineer
AI Engineer
Junior AI Engineer
Data Scientist
Junior Data Scientist
Data Engineer
Junior Data Engineer
Analytics Engineer
DevOps Engineer
Junior DevOps Engineer
Cloud Engineer
Site Reliability Engineer
""".strip().splitlines()
)
SECONDARY_TARGET_ROLES = tuple(
    """
Business Analyst
Systems Analyst
Technical Systems Analyst
IT Business Analyst
Data Analyst
Business Intelligence Analyst
Product Analyst
QA Analyst
Quality Assurance Analyst
Test Analyst
Application Support Analyst
IT Support Analyst
Cloud Support Engineer
Cloud Operations Analyst
Functional Analyst
Analyste de systèmes
Analyste de données
Ingénieur logiciel junior
Développeur logiciel junior
""".strip().splitlines()
)
TARGET_ROLES = CORE_TARGET_ROLES + SECONDARY_TARGET_ROLES
PRIORITY_TARGET_ROLES = CORE_TARGET_ROLES + SECONDARY_TARGET_ROLES[-2:]

DEFAULT_SEARCH_TERMS = tuple(
    """
Junior Software Engineer
Software Engineer I
Associate Software Engineer
Graduate Software Engineer
New Grad Software Engineer
Software Engineer
Junior Software Developer
Software Developer
Python Developer
Junior Python Developer
Backend Developer
Backend Engineer
Junior Backend Developer
Full Stack Developer
Full Stack Engineer
Automation Engineer
Junior Automation Engineer
Test Automation Engineer
QA Automation Engineer
Machine Learning Engineer
Junior Machine Learning Engineer
ML Engineer
AI Engineer
Junior AI Engineer
Data Scientist
Junior Data Scientist
Data Engineer
Junior Data Engineer
DevOps Engineer
Junior DevOps Engineer
Cloud Engineer
Site Reliability Engineer
Développeur Python junior
""".strip().splitlines()
)

DEFAULT_KEYWORDS = (
    "python", "automation", "machine learning",
    "data pipelines", "pandas", "numpy", "scikit-learn", "pytorch", "pytest",
    "unit testing", "ci/cd", "docker", "rest api", "sql", "git", "scripting",
    "algorithms", "data structures", "cloud", "agile", "troubleshooting", "excel",
)
DEFAULT_COMPANY_CAREER_URLS = (
    "Genetec|https://www.genetec.com/careers",
    "CMLS Financial|https://www.cmls.ca/careers",
    "Shopify|https://www.shopify.com/careers",
    "Coveo|https://www.coveo.com/en/company/careers",
    "Mila|https://mila.quebec/en/careers",
    "Lightspeed|https://www.lightspeedhq.com/careers/",
    "CAE|https://www.cae.com/careers/",
    "Intact|https://careers.intactfc.com/",
    "RBC|https://jobs.rbc.com/ca/en",
    "TD Bank|https://jobs.td.com/en-CA/",
    "Scotiabank|https://jobs.scotiabank.com/",
    "BMO|https://jobs.bmo.com/",
    "National Bank of Canada|https://emplois.bnc.ca/",
    "Desjardins|https://www.desjardins.com/ca/about-us/careers/",
)

GREENHOUSE_SEED_BOARDS = (("Stripe", "stripe"), ("GitLab", "gitlab"), ("Databricks", "databricks"))

MANAGEMENT_TITLE_TERMS = (
    "manager", "director", "vp", "vice president", "head of", "chief",
    "president", "executive", "general manager", "gestionnaire", "directeur", "directrice",
)
TINY_STARTUP_SIGNAL_TERMS = (
    "pre-seed", "seed stage", "seed-stage", "early stage startup",
    "early-stage startup", "small but mighty", "wear many hats", "founding engineer",
    "founding team", "series a startup", "bootstrapped", "small scrappy team",
    "fast paced startup environment", "we're a small team", "we are a small team",
)
KNOWN_ESTABLISHED_COMPANIES = (
    "rbc", "royal bank", "td bank", "td canada trust", "scotiabank", "bmo",
    "bank of montreal", "national bank", "desjardins", "cmls", "coveo", "sun life",
    "manulife", "intact", "cgi", "cae", "bombardier", "air canada", "hydro quebec",
    "loto quebec", "caisse de depot", "bell canada", "rogers", "telus", "videotron",
    "shopify", "lightspeed", "nuvia", "nuvei", "ubisoft", "ericsson", "ibm",
    "microsoft", "google", "amazon", "meta", "salesforce", "sap", "oracle", "cisco",
    "deloitte", "pwc", "ey", "kpmg", "accenture", "loblaw", "metro inc", "canadian tire",
)
COLLECTION_ESTABLISHED_COMPANIES = tuple(
    dict.fromkeys(
        company
        for company in KNOWN_ESTABLISHED_COMPANIES + (
            "stripe", "gitlab", "databricks", "figma", "datadog", "airbnb", "spotify",
        )
        if company != "nuvia"
    )
)

DEFAULT_SCORING_RULES = {
    **ScoringRulesConfig().to_dict(),
    "title_match_weight": 24,
    "experience_match_weight": 14,
    "education_match_weight": 3,
    "skills_match_weight": 30,
    "salary_estimate_weight": 4,
    "remote_preference_weight": 3,
    "montreal_proximity_weight": 8,
    "commute_preference_weight": 2,
    "senior_developer_penalty": 25,
    "seven_years_penalty": 20,
}
