from fastapi import FastAPI, HTTPException
from main import song_cover_pipeline, output_dir
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from models import SongCover, Status, Options, Song
from datetime import datetime
from sqlalchemy.orm import load_only
import threading
# import HTTPe
import os
from redis_om import NotFoundError
from redis import ResponseError, Redis
from dotenv import load_dotenv
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware

from sqlmodel import Field, Session, SQLModel, create_engine, select, Index


origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://localhost:3001"
    "http://192.168.1.100:3000"
    "http://192.168.1.68:3001"
    "http://192.168.1.68:3000"

]

wc = ["*"]
r = Redis(host='localhost', port = 6379, decode_responses=True, password='redispass', username='default')

class ConfigBase(SQLModel):
    voice_model: str = Field(index = True)
    main_gain: int 
    inst_gain: int 
    index_rate: float  
    filter_radius: int 
    rms_mix_rate: float 
    f0_method: str 
    crepe_hop_length: int 
    protect: float 
    pitch_change_all: int 
    reverb_rm_size: float 
    reverb_wet: float 
    reverb_dry: float 
    reverb_damping: float

class NewCoverCreate(ConfigBase):
    song_url: str
    created_date: str

class NewCover(ConfigBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    song_url: str = Field(index = True)
    created_date: str = Field(index = True) 
    output_url: str | None = Field(index = True)

class Status(SQLModel,table=True):
     id: int | None = Field(default=None, primary_key=True)
     message: str = Field(index=True)
     percentage: float = Field(index=True)
     cover_id: int | None = Field(default=None, foreign_key="newcover.id")

class StatusUpdate(SQLModel):
    message: str
    percentage: float


Index("idx_cover_config", NewCover.song_url, NewCover.voice_model, NewCover.main_gain, NewCover.inst_gain, NewCover.index_rate, NewCover.filter_radius, NewCover.rms_mix_rate, NewCover.f0_method, NewCover.crepe_hop_length, NewCover.protect, NewCover.pitch_change_all, NewCover.reverb_rm_size, NewCover.reverb_wet, NewCover.reverb_dry, NewCover.reverb_damping)

engine = create_engine(os.environ['PSQL_URL'], echo=True)
SQLModel.metadata.create_all(engine)

    
def read_cover_status(id):
    with Session(engine) as session:
     statement = select(Status).where(Status.cover_id == id)
     cover_status = session.exec(statement).first()
     if not cover_status: 
        raise HTTPException(status_code=404, detail="status not found")
     else:
        return cover_status

    #  status = session.get(Status, cover_id=id)
    
def update_cover_status(id, percent=float, desc=str):
    try:
        cover =  SongCover.get(id)
        cover.status.percent = percent * 100
        cover.status.message = desc
        if(percent == 1):
            cover.status.progress = "Complete"
        else:
            cover.status.progress = "Processing"
        cover.save()
        return 
    except NotFoundError:
        return {f"Error Updating Status: Cover Not Found"}
    
def update_psql_cover_status(id, update: StatusUpdate):
     db_status = read_cover_status(id)
     with Session(engine) as session:
        status_data = update.model_dump(exclude_unset=True)
        db_status.sqlmodel_update(status_data)
        session.add(db_status)
        session.commit()
        session.refresh(db_status)
        print(db_status)
        return db_status
    
def check_dupe_config(config : NewCoverCreate):
    with Session(engine) as session:
        statement = select(NewCover).where(NewCover.song_url == config.song_url, NewCover.voice_model == config.voice_model, NewCover.main_gain == config.main_gain, NewCover.inst_gain == config.inst_gain, NewCover.index_rate == config.index_rate, NewCover.filter_radius == config.filter_radius, NewCover.rms_mix_rate == config.rms_mix_rate, NewCover.f0_method == config.f0_method, NewCover.crepe_hop_length == config.crepe_hop_length, NewCover.protect == config.protect, NewCover.pitch_change_all == config.pitch_change_all, NewCover.reverb_rm_size == config.reverb_rm_size, NewCover.reverb_wet == config.reverb_wet, NewCover.reverb_dry == config.reverb_dry, NewCover.reverb_damping == config.reverb_damping)
        result = session.exec(statement)
        return result.first()
   
  

def create_psql_cover(options: NewCoverCreate):
    
    duplicate_cover = check_dupe_config(options)
    if(duplicate_cover != None):
        return duplicate_cover
    else:      
        psql_cover = NewCover.model_validate(options)
        with Session(engine) as session: 
            session.add(psql_cover)
            session.commit()
            cover_status = Status(message='Created', percentage='0', cover_id=psql_cover.id)
            session.add(cover_status)
            session.commit()
            session.refresh(psql_cover)
            
            return psql_cover

def get_psql_covers():
    with Session(engine) as session:
        covers = session.exec(select(NewCover).options(load_only(NewCover.song_url, NewCover.crepe_hop_length, NewCover.voice_model))).all()
        return covers
    



async def create_cover(song_id, options, status):
    cover = SongCover(song_id=song_id, options=options, status=status, created=datetime.now())
    cover.save()
    r.sadd(f"song:{song_id}", cover.pk)
    return cover.pk

async def remove_cover(cover_id):
    cover = SongCover.get(cover_id)
    cover.song_id
    # print(f"{cover.song_id}")
    r.srem(f"song{cover.song_id}",cover_id)
    cover.delete()
    return True

async def read_cover(cover_id):
    cover = SongCover.get(cover_id)
    return cover.dict()


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=wc,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# app.mount('/songs', StaticFiles(directory=output_dir), name="songs")
app.mount('/mp3/{song_id}/{cover_id}', StaticFiles(directory='../song_output'), name='mp3')

@app.get('/psql/cover/{song_id}')
def root(song_id):
    now = datetime.now().isoformat(' ')
    default_options = {
        "song_url": song_id,
        "voice_model": "Ado",
        "pitch_change":0,        
        # "keep_files": 0,
        # "is_webui": True,
        "main_gain": 0, 
        "inst_gain": 0,
        "index_rate": 0.5,
        "filter_radius": 3,
        "rms_mix_rate": 0.25,
        "f0_method": 'rmvpe',
        "crepe_hop_length": 128,
        "protect": 0.33,
        "pitch_change_all": 0,
        "reverb_rm_size": 0.15,
        "reverb_wet": 0.2,
        "reverb_dry": 0.8,
        "reverb_damping": 0.7,
        "output_url": 'pending',
        "created_date": now
    }
    config = NewCoverCreate(**default_options)
 
    cover = create_psql_cover(config)
    # cover.id
    # cover.valid
    return f'ayyy lmao {cover.id}'

@app.get('/cover/{song_id}')
async def root(song_id):
    default_options = {
        "voice_model": "Ado",
        "pitch_change":0,        
        "keep_files": 0,
        "is_webui": True,
        "main_gain": 0, 
        "inst_gain": 0,
        "index_rate": 0.5,
        "filter_radius": 3,
        "rms_mix_rate": 0.25,
        "f0_method": 'rmvpe',
        "crepe_hop_length": 128,
        "protect": 0.33,
        "pitch_change_all": 0,
        "reverb_rm_size": 0.15,
        "reverb_wet": 0.2,
        "reverb_dry": 0.8,
        "reverb_damping": 0.7,
        "output_url": 'mp3'
    }

        
    default_status = Status()
    options = Options(**default_options)
    cover_id = await create_cover(song_id=song_id, options=options, status=default_status)
    
    
        # song.covers.push(cover_id)
        # song.save()
    # print(f"{cover.pk}")
    threadkwargs = default_options.copy()
    threadkwargs.update({'progress': update_cover_status, "cover_id":cover_id, 'song_input': f'https://youtube.com/watch?v={song_id}'})
    # threadkwargs.update({})
    # threadkwargs.update({ })
    # print(f"{threadkwargs}")
    thread = threading.Thread(target=song_cover_pipeline, kwargs=threadkwargs)
    thread.start()
    return cover_id

@app.get('/cover/id/{cover_id}')
async def root(cover_id):
    try:
        cover = SongCover.get(cover_id)
        return cover
    except NotFoundError:
        return {'Error: cover not found!'}

@app.get('/psql/covers')
def root():
    covers = get_psql_covers()
    # print(f'{covers}')
    return covers
        


@app.get('/cover/{cover_id}/read')
async def root(cover_id):
    res = await read_cover(cover_id)
    cover_dir = os.listdir(f"{output_dir}/{res['song_id']}/{cover_id}")
    cover_path = os.path.join(output_dir, res["song_id"], cover_id, cover_dir[0])
    def iterfile():
        with open(cover_path, mode='rb') as file_like:
            yield from file_like

    return StreamingResponse(iterfile(), media_type='audio/mp3')

@app.get('/song/{song_id}')
async def root(song_id):
    song =  r.smembers(f'song:{song_id}')
    print(song)
    return song

@app.delete('/song/{song_id}/delete')
async def root(song_id):
    cover_ids = r.smembers(f'song:{song_id}')
    # for id in cover_ids:
    #    print(f'removing {id}')
    #    await remove_cover(id)
    r.delete(f'song:{song_id}')




@app.get('/songs')
async def root():
    song_list = r.keys('*song*')
    return song_list
  
@app.get('/covers/{song_id}')
async def root(song_id):
    cover_ids = r.smembers(f'song:{song_id}')
    return cover_ids

@app.get('/cover/{cover_id}/vocals')
async def root(cover_id):
    res = await read_cover(cover_id)
    cover_dir = os.listdir(f"{output_dir}/{res['song_id']}/{cover_id}")
    vocals_path = os.path.join(output_dir, res["song_id"], cover_id, "vocals.mp3")
    def iterfile():
        with open(vocals_path, mode='rb') as file_like:
            yield from file_like

    return StreamingResponse(iterfile(), media_type='audio/mp3')

@app.patch('/status/{cover_id}')
def root(cover_id,  new_status: StatusUpdate):
   status = update_psql_cover_status(cover_id, new_status)
   return status

@app.get('/status/{cover_id}')
def root(cover_id):
    status = read_cover_status(cover_id)
    print(f'{status}')
    return status
    