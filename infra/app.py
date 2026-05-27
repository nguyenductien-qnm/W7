#!/usr/bin/env python3
import aws_cdk as cdk

from studybot_infra.studybot_stack import StudyBotInfraStack


app = cdk.App()

StudyBotInfraStack(
    app,
    "StudyBotInfraStack",
    env=cdk.Environment(region="ap-southeast-1"),
)

app.synth()
