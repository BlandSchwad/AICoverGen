# from typing import Optional
from fastapi import FastAPI, HTTPException
from main import song_cover_pipeline, output_dir
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from models import SongCover, Status, Options, Song
from datetime import datetime
from sqlalchemy.orm import load_only
import threading

import os
from redis_om import NotFoundError
from redis import ResponseError, Redis
from dotenv import load_dotenv
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware

from sqlmodel import Field, Session, SQLModel, create_engine, select, Index, Relationship
from sql_models import NewCoverCreate, NewCover, StatusUpdate, engine

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



SQLModel.metadata.create_all(engine)

    
def read_cover_status(id):
    with Session(engine) as session:
     db_cover = session.get(NewCover, id)
     if not db_cover: 
        raise HTTPException(status_code=404, detail="Cover not found")
     else:
        return {db_cover.status_message, db_cover.status_percentage }

    #  status = session.get(Status, cover_id=id)
    
def update_psql_cover_status(id, update: StatusUpdate):
    #  db_cover = read_cover_status(id)
     with Session(engine) as session:
        db_cover = session.exec(select(NewCover).where(NewCover.id == id).options(load_only(NewCover.status_message, NewCover.status_percentage))).one()
        if not db_cover:
            raise HTTPException(status_code=404, detail='Cover Not Found')
        else:
            
            status_data = update.model_dump(exclude_unset=True)

            db_cover.sqlmodel_update(status_data)
            session.add(db_cover)
            session.commit()
            session.refresh(db_cover)
            return db_cover
    
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
            session.refresh(psql_cover)
            return psql_cover

def get_psql_covers():
    with Session(engine) as session:
        covers = session.exec(select(NewCover).options(load_only(NewCover.song_url, NewCover.crepe_hop_length, NewCover.voice_model))).all()
        return covers
    

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
 
    db_cover = create_psql_cover(config)
    
    threadkwargs = dump_to_pipline_kwargs(db_cover)
    print(f'{threadkwargs}')
    start_pipeline(threadkwargs)
    return f'ayyy lmao {db_cover.id}'

def dump_to_pipline_kwargs(cover: NewCover):
    dump = cover.model_dump()
    del dump['output_url'], dump['created_date'], dump['id'], dump['song_url'], dump['status_message'], dump['status_percentage']
   
    dump.update({ "progress": update_psql_cover_status , 'song_input': f'https://youtube.com/watch?v={cover.song_url}', "output_format": 'mp3', "is_webui": True, "cover_id":cover.id, "keep_files": 0} )
    return dump

def start_pipeline(kwargs):
    thread = threading.Thread(target=song_cover_pipeline, kwargs=kwargs)
    thread.start()

def read_psql_cover(id):
    with Session(engine) as session:
        cover = session.get(NewCover, id)
        # print(f'{cover}')
        if not cover:
            raise HTTPException
        else:
            return cover
def delete_psql_cover(id):
    db_cover = read_psql_cover(id)
    with Session(engine) as session:
        session.delete(db_cover)
        session.commit()
        return {"ok": True}



@app.get('/psql/covers')
def root():
    covers = get_psql_covers()
    # print(f'{covers}')
    return covers
        

@app.get('/psql/cover/{cover_id}/vocals')
def root(cover_id):
    cover = read_psql_cover(cover_id)
    vocals_path = os.path.join(f'{output_dir}/{cover.song_url}/{cover_id}', "vocals.mp3")
    # return vocals_path
    def iterfile():
        with open(vocals_path, mode='rb') as file_like:
            yield from file_like
    
    return StreamingResponse(iterfile(), media_type='audio/mp3')
    

@app.patch('/status/{cover_id}')
def root(cover_id,  new_status: StatusUpdate):
#    print(f'attempting status change: {new_status}')
   status = update_psql_cover_status(cover_id, new_status)
   return status

@app.get('/status/{cover_id}')
def root(cover_id):
    status = read_cover_status(cover_id)
    return status
    
@app.delete('/cover/{cover_id}')
def root(cover_id):
   return delete_psql_cover(cover_id)

@app.get('/cover/{cover_id}/info')
def root(cover_id):
    return read_psql_cover(cover_id)