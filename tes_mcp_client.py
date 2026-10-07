"""
================================================================================
TES MCP SERVER LEWAT PYTHON (TANPA INSPECTOR/NODE.JS)
================================================================================
"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Parameter untuk menjalankan mcp_server.py sebagai proses terpisah
server_params = StdioServerParameters(
    command="python",          # perintah untuk menjalankan Python
    args=["mcp_server.py"],    # nama file server yang mau dites
)


async def main():
    print("Menyambungkan ke MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Berhasil terhubung!\n")

            # 1. Tampilkan daftar tools yang tersedia
            tools_result = await session.list_tools()
            print("=== DAFTAR TOOLS YANG TERSEDIA ===")
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description}")
            print()

            # 2. Panggil tool get_table_schema
            print("=== TES: get_table_schema ===")
            result = await session.call_tool("get_table_schema", arguments={})
            for content in result.content:
                print(content.text)
            print()

            # 3. Panggil tool query_database dengan query contoh
            print("=== TES: query_database ===")
            result = await session.call_tool(
                "query_database",
                arguments={"sql_query": "SELECT TOP 5 VESSEL_NAME, AMOUNT_G_L_TRANSPORT FROM input_discharge"}
            )
            for content in result.content:
                print(content.text)


if __name__ == "__main__":
    asyncio.run(main())