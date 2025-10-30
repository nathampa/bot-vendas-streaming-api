from sqlmodel import SQLModel

# Schema para o corpo (JSON) do pedido de login
class LoginRequest(SQLModel):
    email: str
    senha: str

# Schema para a resposta (JSON) do token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"