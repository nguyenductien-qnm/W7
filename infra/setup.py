import setuptools


setuptools.setup(
    name="studybot-infra",
    version="0.1.0",
    description="StudyBot infrastructure (AWS CDK)",
    packages=setuptools.find_packages(),
    install_requires=[
        "aws-cdk-lib>=2.0.0,<3.0.0",
        "constructs>=10.0.0,<11.0.0",
    ],
)
