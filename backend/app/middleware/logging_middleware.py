import time
from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        client_ip = request.client.host if request.client else "Unknown"
        logger.info(f"👉 请求开始 | {request.method} | {request.url.path} | Client: {client_ip}")
        
        # Process request
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Log response
            log_msg = f"👈 请求结束 | {request.method} | {request.url.path} | Status: {response.status_code} | Time: {process_time:.4f}s"
            
            # Highlight slow queries
            if process_time > 1.0:
                logger.warning(f"{log_msg} 🐌 (慢请求)")
            elif response.status_code >= 400:
                logger.error(log_msg)
            else:
                logger.info(log_msg)
                
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.exception(f"❌ 请求崩溃 | {request.method} | {request.url.path} | Time: {process_time:.4f}s | Error: {str(e)}")
            raise e
