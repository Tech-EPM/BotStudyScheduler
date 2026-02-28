from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.db.models import SessionFile
from bot.utils.file_storage import save_session_file, allowed_file, delete_file_async
from typing import List, Optional
import asyncio
from functools import partial

class SessionFileService:
    def __init__(self, db: AsyncSession):  
        self.db = db

    async def upload_file(
        self, 
        session_id: str, 
        file_bytes: bytes, 
        original_filename: str,
        category: str = "other"
    ) -> Optional[SessionFile]:
        """Асинхронная загрузка файла"""
        

        if not allowed_file(original_filename):
            raise ValueError(f"Файл {original_filename} имеет запрещенное расширение")


        storage_path = f"session_files/{category}"
        relative_path = await save_session_file(  # 
            file_bytes, original_filename, storage_path
        )


        db_file = SessionFile(
            session_id=session_id,
            original_filename=original_filename,
            stored_path=relative_path,
            file_size=len(file_bytes),
            category=category
        )
        
        self.db.add(db_file)
        await self.db.commit()  
        await self.db.refresh(db_file)  
        
        return db_file

    async def get_session_files(
        self, session_id: str, category: str = None
    ) -> List[SessionFile]:
        """Асинхронный запрос файлов"""
        query = select(SessionFile).where(SessionFile.session_id == session_id)
        
        if category:
            query = query.where(SessionFile.category == category)
            
        result = await self.db.execute(query)
        return result.scalars().all()

    async def delete_file(self, file_id: int) -> bool: 
        """Асинхронное удаление файла"""

        stmt = select(SessionFile).where(SessionFile.id == file_id)
        result = await self.db.execute(stmt)
        db_file = result.scalar_one_or_none()
        
        if not db_file:
            return False
            
    
        await delete_file_async(db_file.stored_path)
       

        await self.db.delete(db_file)
        await self.db.commit()
        
        return True

    async def delete_all_session_files(self, session_id: str):
        """Очистка всех файлов сессии"""
        files = await self.get_session_files(session_id)
        for f in files:
            await self.delete_file(f.id)