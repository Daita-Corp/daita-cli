"""
My Workflow - Data Pipeline
"""
from daita import Agent, Workflow


def create_workflow():
    workflow = Workflow("Data Pipeline")
    validator = Agent(name="Data Validator", model="gpt-4o-mini",
                      prompt="You validate data quality.")
    analyzer = Agent(name="Data Analyzer", model="gpt-4o-mini",
                     prompt="You analyze data and extract insights.")
    workflow.add_agent("validator", validator)
    workflow.add_agent("analyzer", analyzer)
    workflow.connect("validator", "validated_data", "analyzer")
    return workflow


if __name__ == "__main__":
    import asyncio

    async def main():
        wf = create_workflow()
        await wf.start()
        await wf.stop()

    asyncio.run(main())
