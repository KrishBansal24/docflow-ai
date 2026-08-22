import asyncio
import logging
from services.approval_service import ApprovalService
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

async def main():
    service = ApprovalService()
    await service.process_notion_updates()
    await asyncio.sleep(5)

asyncio.run(main())
