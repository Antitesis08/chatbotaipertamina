
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Lokasi MCP Server
MCP_SERVER_PATH = str(Path(__file__).parent / "mcp_server.py")

server_params = StdioServerParameters(
    command="python",
    args=[MCP_SERVER_PATH]
)

async def test_query(label, sql_query):
    print(f"\n===== {label} =====")
    print("Query:")
    print(sql_query)

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "query_database",
                    arguments={"sql_query": sql_query}
                )

                print("\nHasil MCP:")

                for item in result.content:
                    if hasattr(item, "text"):
                        print(item.text)

                print("\nStatus isError:", result.isError)

    except Exception as e:
        print("\nMCP gagal dijalankan:", str(e))


async def main():

    # KU-CA-13: Query SELECT
    select_query = """
    SELECT TOP 5 VESSEL_NAME, SUM(R4_N) AS TOTAL_R4_N
    FROM dbo.input_discharge
    WHERE ALAT_ANGKUT = 'KAPAL'
    GROUP BY VESSEL_NAME
    ORDER BY TOTAL_R4_N ASC;
    """

    await test_query("KU-CA-13 - SELECT", select_query)

    # KU-CA-14: Query DELETE
    delete_query = """
    DELETE FROM dbo.input_discharge;
    """

    await test_query("KU-CA-14 - DELETE", delete_query)


if __name__ == "__main__":
    asyncio.run(main())
