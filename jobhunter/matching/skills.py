"""Skill taxonomy and whole-word skill extraction.

Each entry is ``id -> (display label, category, aliases)``. Aliases are matched
as whole words after :func:`skill_text` normalization (which, unlike
``normalize_text``, keeps ``+ # . /`` so ``c++``, ``c#``, ``.net``, ``node.js``
and ``ci/cd`` survive). Ambiguous one-letter names (``c``, ``r``, ``go``) are
only matched through unambiguous aliases (``golang``, ``rstudio``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

try:
    from jobhunter.textutils import strip_accents
except ModuleNotFoundError:  # pragma: no cover
    from textutils import strip_accents

SKILLS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # --- languages
    "python": ("Python", "language", ("python", "python3", "django rest framework")),
    "java": ("Java", "language", ("java", "j2ee", "jvm")),
    "javascript": ("JavaScript", "language", ("javascript", "js", "ecmascript", "es6")),
    "typescript": ("TypeScript", "language", ("typescript",)),
    "c++": ("C++", "language", ("c++", "cpp")),
    "c#": ("C#", "language", ("c#", "csharp", "c sharp")),
    ".net": (".NET", "framework", (".net", "dotnet", "asp.net", "net core", "dotnet core")),
    "go": ("Go", "language", ("golang",)),
    "rust": ("Rust", "language", ("rust",)),
    "php": ("PHP", "language", ("php", "laravel", "symfony")),
    "ruby": ("Ruby", "language", ("ruby", "ruby on rails")),
    "kotlin": ("Kotlin", "language", ("kotlin",)),
    "swift": ("Swift", "language", ("swiftui", "swift programming", "swift developer", "swift language")),
    "scala": ("Scala", "language", ("scala",)),
    "r": ("R", "language", ("r programming", "rstudio", "r studio", "r language")),
    "matlab": ("MATLAB", "language", ("matlab",)),
    "bash": ("Bash/shell scripting", "language", ("bash", "shell scripting", "shell script", "shell scripts")),
    "powershell": ("PowerShell", "language", ("powershell",)),
    "sql": ("SQL", "database", ("sql", "t sql", "tsql", "pl sql", "plsql", "pl/sql", "t-sql")),
    # --- databases / messaging
    "postgresql": ("PostgreSQL", "database", ("postgresql", "postgres", "psql")),
    "mysql": ("MySQL", "database", ("mysql", "mariadb")),
    "sql server": ("SQL Server", "database", ("sql server", "mssql", "microsoft sql server")),
    "sqlite": ("SQLite", "database", ("sqlite",)),
    "oracle": ("Oracle DB", "database", ("oracle database", "oracle db", "oracle sql")),
    "mongodb": ("MongoDB", "database", ("mongodb", "mongo db", "mongo")),
    "nosql": ("NoSQL", "database", ("nosql", "dynamodb", "cassandra")),
    "redis": ("Redis", "database", ("redis",)),
    "elasticsearch": ("Elasticsearch", "database", ("elasticsearch", "elastic search", "opensearch")),
    "kafka": ("Kafka", "messaging", ("kafka",)),
    "rabbitmq": ("RabbitMQ", "messaging", ("rabbitmq",)),
    "pub/sub": ("Pub/Sub", "messaging", ("pub/sub", "pubsub", "pub sub", "message queue", "message queues")),
    # --- web / backend
    "react": ("React", "framework", ("react", "react.js", "reactjs")),
    "react native": ("React Native", "mobile", ("react native",)),
    "angular": ("Angular", "framework", ("angular", "angularjs")),
    "vue": ("Vue", "framework", ("vue", "vue.js", "vuejs")),
    "svelte": ("Svelte", "framework", ("svelte", "sveltekit")),
    "next.js": ("Next.js", "framework", ("next.js", "nextjs")),
    "node.js": ("Node.js", "framework", ("node.js", "nodejs", "node js")),
    "express": ("Express", "framework", ("express.js", "expressjs", "express js")),
    "django": ("Django", "framework", ("django",)),
    "flask": ("Flask", "framework", ("flask",)),
    "fastapi": ("FastAPI", "framework", ("fastapi",)),
    "spring": ("Spring", "framework", ("spring boot", "springboot", "spring framework")),
    "html/css": ("HTML/CSS", "web", ("html", "css", "html5", "css3", "sass", "scss")),
    "rest api": ("REST APIs", "web", ("rest", "rest api", "rest apis", "restful", "api", "apis", "web services", "api rest")),
    "graphql": ("GraphQL", "web", ("graphql",)),
    "microservices": ("Microservices", "architecture", ("microservices", "microservice", "microservices architecture")),
    "orm": ("ORM", "web", ("orm", "hibernate", "sqlalchemy", "prisma", "prisma orm")),
    "streamlit": ("Streamlit", "framework", ("streamlit",)),
    # --- mobile
    "android": ("Android", "mobile", ("android",)),
    "ios": ("iOS", "mobile", ("ios",)),
    "flutter": ("Flutter", "mobile", ("flutter", "dart")),
    "expo": ("Expo", "mobile", ("expo",)),
    # --- cloud / devops
    "aws": ("AWS", "cloud", ("aws", "amazon web services", "ec2", "s3", "cloudformation")),
    "azure": ("Azure", "cloud", ("azure", "microsoft azure")),
    "gcp": ("GCP", "cloud", ("gcp", "google cloud", "google cloud platform")),
    "cloud": ("Cloud", "cloud", ("cloud", "cloud computing", "cloud infrastructure", "infonuagique")),
    "terraform": ("Terraform", "devops", ("terraform",)),
    "ansible": ("Ansible", "devops", ("ansible",)),
    "infrastructure as code": ("Infrastructure as code", "devops", ("infrastructure as code", "iac", "infrastructure en tant que code")),
    "docker": ("Docker", "devops", ("docker", "containerization", "docker containers", "conteneurs docker")),
    "kubernetes": ("Kubernetes", "devops", ("kubernetes", "k8s", "eks", "aks", "gke", "helm")),
    "ci/cd": ("CI/CD", "devops", ("ci/cd", "cicd", "ci cd", "continuous integration", "continuous delivery", "continuous deployment", "integration continue")),
    "jenkins": ("Jenkins", "devops", ("jenkins",)),
    "github actions": ("GitHub Actions", "devops", ("github actions",)),
    "gitlab ci": ("GitLab CI", "devops", ("gitlab ci", "gitlab ci/cd")),
    "linux": ("Linux", "devops", ("linux", "unix", "ubuntu", "rhel", "centos")),
    "git": ("Git", "devops", ("git", "github", "gitlab", "bitbucket", "version control", "gestion de versions")),
    "prometheus": ("Prometheus/Grafana", "devops", ("prometheus", "grafana")),
    "datadog": ("Datadog", "devops", ("datadog", "splunk", "new relic", "observability")),
    "networking": ("Networking", "it", ("computer networking", "network administration", "tcp/ip", "dns", "dhcp", "vpn", "lan/wan")),
    # --- data / ML
    "pandas": ("pandas", "data", ("pandas",)),
    "numpy": ("NumPy", "data", ("numpy", "scipy")),
    "scikit-learn": ("scikit-learn", "ml", ("scikit learn", "scikit-learn", "sklearn")),
    "pytorch": ("PyTorch", "ml", ("pytorch", "torch", "torchvision")),
    "tensorflow": ("TensorFlow", "ml", ("tensorflow",)),
    "keras": ("Keras", "ml", ("keras",)),
    "machine learning": ("Machine learning", "ml", ("machine learning", "ml", "apprentissage automatique", "classification", "clustering", "decision tree", "decision trees", "random forest", "k means")),
    "deep learning": ("Deep learning", "ml", ("deep learning", "neural network", "neural networks", "cnn", "cnns", "mlp", "resnet", "apprentissage profond", "reseaux de neurones")),
    "computer vision": ("Computer vision", "ml", ("computer vision", "vision par ordinateur", "image classification", "image recognition", "opencv")),
    "nlp": ("NLP", "ml", ("nlp", "natural language processing", "traitement du langage naturel")),
    "llm": ("LLMs/generative AI", "ml", ("llm", "llms", "large language model", "large language models", "generative ai", "gen ai", "genai", "openai", "langchain", "ia generative")),
    "artificial intelligence": ("Artificial intelligence", "ml", ("artificial intelligence", "ai", "intelligence artificielle")),
    "mlops": ("MLOps", "ml", ("mlops", "model deployment", "model serving")),
    "spark": ("Spark", "data", ("pyspark", "apache spark", "spark sql", "spark streaming", "hadoop")),
    "airflow": ("Airflow", "data", ("airflow", "dagster", "prefect")),
    "dbt": ("dbt", "data", ("dbt",)),
    "etl": ("ETL/data pipelines", "data", ("etl", "elt", "data pipeline", "data pipelines", "pipelines de donnees")),
    "data warehouse": ("Data warehousing", "data", ("data warehouse", "data warehousing", "snowflake", "bigquery", "redshift", "databricks", "entrepot de donnees")),
    "tableau": ("Tableau", "bi", ("tableau", "looker", "qlik")),
    "power bi": ("Power BI", "bi", ("power bi", "powerbi")),
    "excel": ("Excel", "bi", ("excel", "microsoft excel", "spreadsheets", "vba")),
    "data analysis": ("Data analysis", "data", ("data analysis", "data analytics", "analytics", "analyse de donnees", "analyse des donnees")),
    "data visualization": ("Data visualization", "data", ("data visualization", "data visualisation", "visualisation de donnees", "dashboards", "dashboard")),
    "statistics": ("Statistics", "data", ("statistics", "statistical analysis", "statistiques", "statistical modeling")),
    # --- testing / QA
    "pytest": ("pytest", "testing", ("pytest",)),
    "junit": ("JUnit", "testing", ("junit", "testng", "mockito", "jest", "mocha")),
    "unit testing": ("Unit testing", "testing", ("unit testing", "unit tests", "unit test", "tests unitaires", "integration testing", "integration tests", "tdd", "test driven development")),
    "test automation": ("Test automation", "testing", ("test automation", "automated testing", "automated tests", "qa automation", "automation testing", "test automation framework", "automatisation des tests")),
    "selenium": ("Selenium", "testing", ("selenium", "webdriver")),
    "cypress": ("Cypress/Playwright", "testing", ("cypress", "playwright")),
    "postman": ("Postman", "testing", ("postman", "soapui")),
    "qa": ("QA/testing", "testing", ("qa", "quality assurance", "assurance qualite", "software testing", "test cases", "test plans", "test plan")),
    # --- practices / tools
    "agile": ("Agile/Scrum", "practice", ("agile", "scrum", "kanban", "sprints", "sprint planning")),
    "jira": ("Jira", "practice", ("jira", "confluence", "azure devops")),
    "code review": ("Code review", "practice", ("code review", "code reviews", "pull requests", "peer review")),
    "oop": ("Object-oriented design", "practice", ("object oriented", "oop", "design patterns", "programmation orientee objet", "poo")),
    "algorithms": ("Data structures & algorithms", "practice", ("algorithms", "data structures", "algorithmes", "structures de donnees")),
    "automation": ("Automation/scripting", "practice", ("automation", "automatisation", "automating", "automate", "scripting", "automation scripting", "scripts d automatisation")),
    "rpa": ("RPA", "practice", ("rpa", "uipath", "automation anywhere", "blue prism", "power automate")),
    # --- support / analysis
    "troubleshooting": ("Troubleshooting", "support", ("troubleshooting", "debugging", "depannage", "diagnostic")),
    "incident management": ("Incident management", "support", ("incident management", "incident", "incidents", "gestion des incidents")),
    "root cause analysis": ("Root cause analysis", "support", ("root cause analysis", "rca", "root cause", "causes racines", "analyse des causes")),
    "itil": ("ITIL", "support", ("itil",)),
    "service desk": ("IT support / service desk", "support", ("service desk", "help desk", "helpdesk", "technical support", "it support", "support technique", "soutien informatique", "end user support", "desktop support")),
    "servicenow": ("ServiceNow", "support", ("servicenow", "service now")),
    "active directory": ("Active Directory", "support", ("active directory", "azure ad", "entra id", "intune")),
    "microsoft 365": ("Microsoft 365", "support", ("microsoft 365", "office 365", "m365", "o365")),
    "technical documentation": ("Technical documentation", "support", ("technical documentation", "documentation technique", "knowledge base", "knowledge base articles", "documentation")),
    "requirements gathering": ("Requirements gathering", "analysis", ("requirements gathering", "requirements analysis", "business requirements", "requirements elicitation", "gather requirements", "gathered requirements", "gathering requirements", "gathers requirements", "recueil des besoins", "recueilli les besoins", "collecte des exigences")),
    "business analysis": ("Business analysis", "analysis", ("business analysis", "business analyst", "analyse d affaires", "analyse des besoins")),
    "stakeholder communication": ("Stakeholder communication", "analysis", ("stakeholder", "stakeholders", "parties prenantes")),
    "process improvement": ("Process improvement", "analysis", ("process improvement", "continuous improvement", "improve processes", "improved processes", "improving processes", "improve support processes", "amelioration des processus", "amelioration continue")),
    "uat": ("UAT", "analysis", ("uat", "user acceptance testing")),
    "project management": ("Project management", "analysis", ("project management", "gestion de projet", "pmp")),
    "sap": ("SAP", "enterprise", ("sap", "sap erp", "abap")),
    "salesforce": ("Salesforce", "enterprise", ("salesforce", "salesforce apex")),
    "sharepoint": ("SharePoint", "enterprise", ("sharepoint", "power apps", "power platform")),
    # --- security
    "cybersecurity": ("Cybersecurity", "security", ("cybersecurity", "cyber security", "information security", "securite informatique", "infosec", "siem", "penetration testing")),
    "oauth": ("OAuth/IAM", "security", ("oauth", "oauth2", "iam", "sso", "saml")),
}

# Skills whose absence from a candidate's profile is a *hard* gap when the posting
# leans on them (a "Java developer" role is not a fit for someone without Java).
PRIMARY_STACK = frozenset(
    {
        "java", "c#", ".net", "c++", "php", "ruby", "go", "rust", "kotlin", "swift",
        "scala", "sap", "salesforce", "angular", "vue", "kubernetes", "r", "matlab",
    }
)

# Candidate-side implications (a PyTorch user does machine-learning work, etc.).
IMPLIED_SKILLS: dict[str, tuple[str, ...]] = {
    "gcp": ("cloud",),
    "aws": ("cloud",),
    "azure": ("cloud",),
    "pytorch": ("machine learning",),
    "tensorflow": ("machine learning",),
    "keras": ("machine learning",),
    "scikit-learn": ("machine learning",),
    "pytest": ("unit testing",),
    "junit": ("unit testing",),
    "sqlite": ("sql",),
    "postgresql": ("sql",),
    "mysql": ("sql",),
    "sql server": ("sql",),
    "pandas": ("data analysis",),
    "terraform": ("infrastructure as code",),
    "ansible": ("infrastructure as code",),
}

# "Closest experience" relationships, used only to word an honest gap statement
# ("I have not used X, my closest experience is Y"), never to claim X.
RELATED_SKILLS: dict[str, tuple[str, ...]] = {
    "aws": ("gcp", "azure"), "azure": ("gcp", "aws"), "gcp": ("aws", "azure"),
    "tensorflow": ("pytorch", "keras"), "keras": ("pytorch", "tensorflow"),
    "pytorch": ("tensorflow", "scikit-learn"),
    "mysql": ("sql", "postgresql", "sqlite"), "postgresql": ("sql", "mysql", "sqlite"),
    "sql server": ("sql", "postgresql", "mysql"), "oracle": ("sql", "postgresql"),
    "react": ("react native", "javascript", "svelte"),
    "angular": ("react", "typescript", "javascript", "svelte"),
    "vue": ("react", "svelte", "javascript"), "svelte": ("react", "javascript"),
    "typescript": ("javascript",), "next.js": ("react", "svelte", "javascript"),
    "jenkins": ("ci/cd", "github actions"), "gitlab ci": ("ci/cd", "github actions"),
    "github actions": ("ci/cd",),
    "kubernetes": ("docker",), "selenium": ("pytest", "test automation"),
    "cypress": ("selenium", "test automation", "javascript"),
    "tableau": ("power bi", "excel"), "power bi": ("excel", "tableau"),
    "spark": ("pandas", "etl"), "airflow": ("etl", "python"),
    "django": ("flask", "fastapi", "python"), "flask": ("django", "fastapi", "python"),
    "fastapi": ("flask", "django", "python"), "spring": ("java",),
    "express": ("node.js",), "node.js": ("javascript", "express"),
    ".net": ("c#", "java"), "c#": ("java",), "kotlin": ("java",),
    "swift": ("react native",), "terraform": ("ansible",),
    "servicenow": ("itil", "incident management"),
}

_FRENCH_AI = re.compile(r"(?<![a-z])[a-z]'ai(?![a-z])")
_SKILL_CHARS = re.compile(r"[^a-z0-9+#./]+")
_SPECIAL_DOT = re.compile(r"^[a-z0-9+#]+\.[a-z0-9]+$")


def skill_text(value: str) -> str:
    """Lowercase, accent-folded text that keeps ``+ # . /`` inside tokens."""
    lowered = strip_accents(value or "").lower().replace("’", "'")
    # French elisions ("j'ai", "n'ai", "qu'ai") are not the skill "AI"
    lowered = _FRENCH_AI.sub(" ", lowered)
    lowered = _SKILL_CHARS.sub(" ", lowered)
    tokens: list[str] = []
    for token in lowered.split():
        token = token.rstrip(".")
        if token.startswith(".") and token != ".net":
            token = token.lstrip(".")
        token = token.strip("/")
        if "." in token and not _SPECIAL_DOT.match(token) and token != ".net":
            token = token.replace(".", " ")
        if token:
            tokens.append(token)
    return " ".join(tokens)


def label_for(skill_id: str) -> str:
    entry = SKILLS.get(skill_id)
    return entry[0] if entry else skill_id


class SkillMatcher:
    """Finds taxonomy skills (plus optional custom terms) in free text."""

    def __init__(self, extra_terms: Iterable[str] = ()):
        self._patterns: dict[str, re.Pattern[str]] = {}
        for skill_id, (_, _, aliases) in SKILLS.items():
            self._patterns[skill_id] = self._compile(aliases)
        self.custom: dict[str, str] = {}
        for term in extra_terms:
            normalized = skill_text(term)
            if not normalized or self.extract(term):
                continue
            custom_id = normalized
            self.custom[custom_id] = term.strip()
            self._patterns[custom_id] = self._compile((term,))

    @staticmethod
    def _compile(aliases: Iterable[str]) -> re.Pattern[str]:
        parts = sorted({re.escape(skill_text(alias)) for alias in aliases if skill_text(alias)}, key=len, reverse=True)
        return re.compile(r"(?<![a-z0-9+#.])(?:" + "|".join(parts) + r")(?![a-z0-9+#])")

    def extract(self, text: str) -> dict[str, int]:
        """Return ``{skill_id: mention_count}`` for skills found in ``text``."""
        normalized = skill_text(text)
        if not normalized:
            return {}
        normalized = normalized.replace("tableaux de bord", "dashboards").replace("tableau de bord", "dashboard")
        found: dict[str, int] = {}
        for skill_id, pattern in self._patterns.items():
            count = len(pattern.findall(normalized))
            if count:
                found[skill_id] = count
        return found

    def label(self, skill_id: str) -> str:
        return self.custom.get(skill_id) or label_for(skill_id)


@lru_cache(maxsize=32)
def get_matcher(extra_terms: tuple[str, ...] = ()) -> SkillMatcher:
    return SkillMatcher(extra_terms)


def expand_inventory(skill_ids: Iterable[str]) -> set[str]:
    """Add implied skills (GCP -> cloud, pytest -> unit testing, ...)."""
    expanded = set(skill_ids)
    for skill_id in list(expanded):
        expanded.update(IMPLIED_SKILLS.get(skill_id, ()))
    return expanded
