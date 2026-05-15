import { Controller, Get, Post, Put, Body, Param } from '@nestjs/common';
import { OrderService } from './order.service';

@Controller('api/order')
export class OrderController {
  constructor(private readonly svc: OrderService) {}

  @Post('create')
  async create(@Body() body: any) {
    return this.svc.create(body);
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    return this.svc.get(+id);
  }

  @Put(':id/status')
  async updateStatus(@Param('id') id: string, @Body() body: any) {
    return this.svc.updateStatus(+id, body.status);
  }
}
