from setuptools import setup, find_packages

setup(
    name="nervus-sdk",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.115",
        "pydantic>=2.0",
        "nats-py>=2.9",
        "redis>=5.0",
        "asyncpg>=0.30",
        "httpx>=0.27",
    ],
    python_requires=">=3.11",
)
