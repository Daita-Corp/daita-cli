"""
My Agent - Data Processing Example
"""
from daita import Agent
from daita.core.tools import tool


@tool
async def calculate_stats(data: list) -> dict:
    """Calculate basic statistics for a list of numbers."""
    if not data:
        return {"error": "No data provided"}
    return {
        "count": len(data),
        "sum": sum(data),
        "avg": sum(data) / len(data),
        "min": min(data),
        "max": max(data),
    }


def create_agent():
    return Agent(
        name="Data Processor",
        model="gpt-4o-mini",
        prompt="You are a data analyst. Help users analyze and process data.",
        tools=[calculate_stats],
    )


if __name__ == "__main__":
    import asyncio

    async def main():
        agent = create_agent()
        await agent.start()
        try:
            answer = await agent.run("Analyze these sales numbers: [100, 250, 175, 300, 225]")
            print(f"Analysis: {answer}")
        finally:
            await agent.stop()

    asyncio.run(main())
