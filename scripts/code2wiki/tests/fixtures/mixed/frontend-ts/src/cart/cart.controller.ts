import { Controller, Get, Post, Body, Param } from '@nestjs/common';

@Controller('api/cart')
export class CartController {

  @Post('add')
  async add(@Body() body: any) {
    return { ok: true };
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    return { id };
  }
}
